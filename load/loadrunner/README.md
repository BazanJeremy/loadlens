# Script DevWeb (LoadRunner)

> 🇬🇧 [English version](README.en.md)

`main.js` charge les trois parcours du système testé avec **OpenText Performance Engineering for
Developers** (ex-LoadRunner Developer, protocole DevWeb). loadlens lit ensuite la base de
résultats que DevWeb écrit (`devWebDB.db`) et rend un verdict sur les SLO. LoadRunner ne tourne
jamais dans la CI : ses résultats sont produits en local puis commités, datés, dans
[`fixtures/loadrunner/`](../../fixtures/loadrunner/PROVENANCE.md) (ADR-001).

## Le script

- Une itération appelle chaque parcours une fois, chacun dans sa transaction : `create_payment`
  (réussie sur 201), `get_payment` et `get_statement` (réussies sur 200). Tout autre code, ou une
  erreur de transport, la marque en échec, et l'itération passe au parcours suivant.
- Identifiants tirés au hasard dans les plages du jeu de données initial, les mêmes que le
  [plan JMeter](../jmeter/README.md).
- `scenario.yml` : **modèle fermé**, 6 utilisateurs virtuels, 10 s de montée puis 60 s de charge,
  rythme `intervals` d'1 s. D'après l'aide DevWeb, ce rythme fixe l'écart entre deux débuts
  d'itération, et une itération attend la fin de la précédente : tant qu'une itération dure
  moins d'une seconde, le débit déclaré est de **6 par seconde et par transaction**. L'aide écrit
  `interval`, que DevWeb 26.3 refuse.

## Lancer en local (PowerShell)

Prérequis : DevWeb extrait dans un dossier (`$DW` ci-dessous), Docker Desktop démarré. `$L` est
la racine du dépôt, `$W` un dossier de travail hors du dépôt (DevWeb y écrit `results\`).

```powershell
New-Item -ItemType Directory -Force $W | Out-Null
Copy-Item "$L\load\loadrunner\main.js", "$L\load\loadrunner\scenario.yml" $W
docker compose -f "$L\compose.yaml" up -d --wait --build
Push-Location $W; & "$DW\DevWeb.exe" -mode=load -summary json $W; Pop-Location
docker compose -f "$L\compose.yaml" down
loadlens verdict --config "$L\config\slo.yaml" --candidate "$W\results\devWebDB.db" `
  --utc-offset +02:00 --warmup-s 10 `
  --target-rps create_payment=6 --target-rps get_payment=6 --target-rps get_statement=6
```

`--utc-offset` est obligatoire : les horodatages de `devWebDB.db` sont en heure locale, sans
fuseau. Le `startTime` du `replay_summary.json` écrit par DevWeb donne le décalage.

## Licence

L'édition gratuite (licence communautaire) est limitée à **50 utilisateurs virtuels**, un test
à la fois, au seul protocole DevWeb, et réservée au développement de tests et aux preuves de
concept ; tout usage commercial est interdit (OpenText, Additional License Authorizations
5200-1957, lue le 16/10/2026). Ses binaires ne sont ni commités, ni téléchargés dans la CI. Cette
même licence interdit de publier des comparaisons détaillées avec d'autres outils : loadlens ne
publie aucun chiffre JMeter et LoadRunner côte à côte.

## Limites connues (v1)

- **Verdict sur les SLO seuls** : p99 et taux d'erreur (durs), p95, Apdex et débit (souples).
  `loadlens verdict` refuse une référence (`--baseline`) avec un résultat DevWeb : le détecteur
  de régression n'a été calibré que sur des résultats JMeter
  ([docs/calibration.md](../../docs/calibration.md)).
- **Pas de protocole A-B-B-A ni de parité de verdict côté LoadRunner** : la preuve « la régression
  N+1 finit en FAIL » n'existe que pour la chaîne JMeter.
- Pas de code HTTP par transaction dans `devWebDB.db` ; le début d'une transaction est calculé
  (horodatage de fin moins durée), voir la [provenance](../../fixtures/loadrunner/PROVENANCE.md).
