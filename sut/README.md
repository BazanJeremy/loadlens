# Système testé : API de paiements

> 🇬🇧 [English version](README.en.md)

Une API HTTP de paiements (FastAPI + PostgreSQL), fournie avec loadlens pour que la détection
de régressions s'exerce sur de vrais ralentissements. Trois régressions réalistes sont
activables par variable d'environnement, toutes désactivées par défaut.

## Points d'accès

| Méthode | Chemin | Rôle |
|---|---|---|
| `POST` | `/payments` | Débite un compte au profit d'un marchand. `201`, `404` (compte ou marchand inconnu), `409` (`insufficient_funds`), `422` (corps invalide) |
| `GET` | `/payments/{id}` | Lit un paiement. `200`, `404`, `422` |
| `GET` | `/accounts/{id}/statement` | Relevé paginé, plus récent d'abord. `limit` 1–200 (défaut 50), `cursor` = `next_cursor` de la page précédente |
| `GET` | `/health` | État de la base et régressions actives |

Le débit d'un compte est un `UPDATE … WHERE balance_cents >= montant` atomique : deux paiements
simultanés ne peuvent pas perdre de mise à jour (testé avec 20 paiements concurrents).

## Lancer

```powershell
docker compose up -d --build --wait
python -m pytest sut/tests
docker compose down
```

Chaque `docker compose up` relance le job `seed`, qui **supprime et recharge** la base : chaque
run part des mêmes données.

## Données de départ

Générées de façon déterministe (`payments_api/seed_data.py`, graine `42`) : 1 000 comptes,
5 000 marchands, 100 000 paiements. Réglables par `SEED_ACCOUNTS`, `SEED_MERCHANTS`,
`SEED_PAYMENTS` et `SEED_RANDOM_SEED`. Le dernier compte (n° 1 000 par défaut) est créé **vide et
sans paiement**, pour exercer le cas de fonds insuffisants : un plan de charge ne doit pas le
viser.

## Régressions activables

| Variable | Mécanisme | Où elle se voit |
|---|---|---|
| `SUT_REGRESSION_N_PLUS_ONE=1` | Le relevé ne joint plus les marchands : chaque marchand distinct de la page est chargé par sa propre requête, soit jusqu'à 50 requêtes de plus pour une page de 50 (nombre exact non mesuré) | `GET /accounts/{id}/statement`, même sans concurrence |
| `SUT_REGRESSION_LOCK=1` | Chaque paiement met à jour une même ligne de total journalier dans sa transaction : tous les paiements font la queue sur son verrou jusqu'au commit | `POST /payments` sous concurrence |
| `SUT_REGRESSION_POOL=1` | Pool de connexions réduit à 1 (au lieu de 10 + 10 en débordement) | Toute requête sous concurrence |

Les tests fonctionnels passent à l'identique dans les quatre modes : une régression change les
performances, jamais les résultats.

## Mesures manuelles (17/10/2026)

Source : `sut/measurements/2026-10-17-manual.jsonl`, produit par `sut/tools/measure.py`.

- **Machine :** Intel Core i7-9750H, Windows 10 Home 19045, Docker Desktop (moteur 29.6.1,
  12 CPU, 7,7 Gio alloués). Le client Python tourne sur l'hôte et passe par le proxy de ports de
  Docker Desktop : les valeurs absolues mesurent toute la chaîne. Seules les comparaisons entre
  modes sur cette machine ont un sens.
- **Protocole :** base rechargée avant chaque mode, 50 requêtes de chauffe écartées, ordre
  nominal → N+1 → LOCK → POOL → nominal. **Un seul run par mode** : ce sont des ordres de
  grandeur, pas des références.

p50 / p95 en ms, puis débit en requêtes par seconde :

| Scénario | Nominal | N+1 | LOCK | POOL | Nominal (2ᵉ run) |
|---|---|---|---|---|---|
| Relevé, concurrence 1, 300 req. | 6,0 / 6,8 · 160 | **29,0 / 33,7 · 34** | 6,1 / 7,4 · 157 | 6,8 / 9,5 · 138 | 6,2 / 8,2 · 151 |
| Lecture paiement, concurrence 32, 2 000 req. | 84,2 / 113,4 · 363 | 84,9 / 118,3 · 356 | 98,7 / 143,0 · 308 | **105,9 / 172,6 · 274** | 86,8 / 120,7 · 346 |
| Écriture paiement, concurrence 32, 2 000 req. | 171,9 / 239,2 · 182 | 176,8 / 250,4 · 176 | **171,7 / 589,2 · 137** | 169,2 / 222,3 · 182 | 176,0 / 248,5 · 178 |

Ce que montrent ces mesures :

- **N+1** multiplie la latence médiane du relevé par 4,7 à 4,8 (selon le run nominal de
  référence), même sans concurrence.
- **LOCK** n'agit que sur la queue de distribution : la médiane d'écriture ne bouge pas, mais le
  p95 passe de 239–249 à 589 ms et le p99 d'environ 264–289 à 932 ms. Un indicateur centré sur
  la médiane ne verrait pas cette régression.
- **POOL** dégrade les lectures concurrentes (p95 +43 à +52 %, débit −21 à −25 % par rapport aux
  deux runs nominaux). En écriture, à cette concurrence, aucun effet net n'apparaît : **cause
  inconnue**.
- **Bruit :** entre les deux runs nominaux, le p95 du relevé varie de 6,8 à 8,2 ms (+21 %). Des
  écarts sans mécanisme connu apparaissent aussi (LOCK sur les lectures, POOL sur le relevé à
  concurrence 1) : **cause inconnue**. Ces écarts sont du même ordre que certains seuils ; c'est
  pourquoi loadlens ne conclura pas sur un run isolé.

## Limites

- Schéma créé par `metadata.create_all`, sans migrations : la base est jetable par conception.
- Les identifiants PostgreSQL `sut` / `sut` ne servent qu'à ce conteneur local.
- Une seule instance d'API, un seul processus Uvicorn, sans journal d'accès : c'est une cible de
  mesure, pas un service de production.
