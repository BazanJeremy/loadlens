# Plan JMeter

> 🇬🇧 [English version](README.en.md)

Le plan `loadlens.jmx` charge les trois parcours du système testé, chacun avec son propre débit
d'arrivée (**modèle ouvert**) : un ralentissement du service ne réduit pas la charge envoyée.
JMeter tourne dans un conteneur (`Dockerfile` : JMeter 5.6.3 sur Temurin 21, archive vérifiée
par SHA-512), identique en local et dans la CI : aucun Java n'est nécessaire sur la machine.

## Lancer en local (PowerShell, depuis la racine du dépôt)

```powershell
docker build -t loadlens-jmeter:5.6.3 load/jmeter
docker compose up -d --wait
New-Item -ItemType Directory -Force results | Out-Null
docker run --rm --network loadlens-sut_default `
  -v "${PWD}/load/jmeter:/plan:ro" -v "${PWD}/results:/out" `
  loadlens-jmeter:5.6.3 -n -t /plan/loadlens.jmx -q /plan/loadlens.properties `
  -l /out/jmeter.jtl -j /out/jmeter.log -Jhost=api -Jramp_s=10 -Jhold_s=120
loadlens kpi results/jmeter.jtl --warmup-s 10
docker compose down
```

## Paramètres (`-Jnom=valeur`)

| Propriété | Défaut | Rôle |
|---|---|---|
| `host`, `port` | `127.0.0.1`, `8000` | Cible (`api` / `8000` sur le réseau compose) |
| `ramp_s` | `10` | Montée linéaire de 0 au débit cible |
| `hold_s` | `60` | Palier au débit cible |
| `rate_create_payment` | `4` | Arrivées par seconde sur `POST /payments` |
| `rate_get_payment` | `10` | Arrivées par seconde sur `GET /payments/{id}` |
| `rate_get_statement` | `6` | Arrivées par seconde sur `GET /accounts/{id}/statement` |
| `funded_accounts`, `merchants`, `seeded_payments` | `999`, `5000`, `100000` | Bornes des identifiants tirés au hasard (le compte vide n° 1 000 est exclu) |
| `connect_timeout_ms`, `response_timeout_ms` | `5000`, `30000` | Délais HTTP |

Les graines du planning d'arrivées sont fixes (`101`, `202`, `303`) : deux runs reçoivent le même
planning.

## Bonnes pratiques JMeter appliquées

D'après le [guide officiel](https://jmeter.apache.org/usermanual/best-practices.html) :

- **mode ligne de commande** (`-n`), aucun listener dans le plan ;
- **sortie CSV** limitée aux colonnes utiles, réglée dans `loadlens.properties` (chargé par
  `-q`), sans jamais modifier `jmeter.properties` ;
- **paramètres par propriétés** (`${__P()}` + `-J`), aucune valeur codée en dur ;
- **aucun élément déprécié**, aucune assertion superflue : le code HTTP suffit à juger le succès ;
- **charge en modèle ouvert** (Open Model Thread Group). La documentation le recommande plutôt
  qu'un timer de débit, et le marque « experimental » : la version de JMeter est donc figée.

## Mesure locale du profil CI (17/10/2026)

Source : un run local de `ramp_s=10`, `hold_s=120`, débits 4 / 10 / 6, sur la machine décrite
dans `fixtures/jmeter/PROVENANCE.md`.

- 2 500 échantillons sur 130 s de planning ; sans les 10 s de montée, 2 386 échantillons à
  19,97 requêtes par seconde (cible : 20), 0 erreur.
- Le conteneur a tourné 192,5 s pour 130 s de planning : **cause de l'écart inconnue**.
- Coefficient de variation des latences brutes : 0,47 au global, 0,32 à 0,38 par transaction.
- Les latences d'un JTL sont en millisecondes entières : avec un p95 de 9 ms, une hausse de 10 %
  (0,9 ms) est inférieure à la résolution de la mesure.

## Limites

- Le générateur de charge et le système testé partagent la même machine : JMeter consomme une
  part du processeur que le service n'a plus.
- Le modèle ouvert démarre un fil JMeter par arrivée. Que les connexions HTTP soient réutilisées
  ou non d'une arrivée à l'autre n'a pas été vérifié (la colonne `Connect` vaut souvent 0 ms, ce
  qui ne distingue pas une connexion réutilisée d'une connexion locale de moins d'une
  milliseconde).
