# loadlens

**Verdict de performance argumenté à partir de résultats JMeter et LoadRunner : PASS / WARN / FAIL
fondé sur la statistique, pas sur un seuil isolé.**

[![CI](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml/badge.svg)](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-267%20passing-brightgreen?logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

> 🇬🇧 [English version](README.en.md)

## Le problème

Un test de charge produit des milliers de mesures, mais la question « ce build est-il plus lent
que le précédent ? » se tranche souvent sur un seul chiffre comparé à un seuil, ou à l'œil sur un
graphique. Sur des machines cloud partagées, la variabilité d'une mesure de performance peut être
forte : [Laaber et al. (2019)](https://research.chalmers.se/publication/511491) ont mesuré des
coefficients de variation allant de 0,03 % à plus de 100 % selon les benchmarks et les instances.
Un seuil isolé bloque alors des changements sains, ou laisse passer une vraie régression.

## Ce que fait loadlens

- Lit les résultats d'**Apache JMeter** (JTL au format CSV) et d'**OpenText Performance Engineering
  for Developers** (ex-LoadRunner Developer : base `devWebDB.db` du protocole DevWeb), et les ramène
  à un schéma commun.
- Calcule les KPI : percentiles de latence, taux d'erreur, débit, Apdex, coefficient de variation,
  par transaction et pour l'ensemble.
- Vérifie les SLO et, quand une référence mesurée sur la même machine est fournie, cherche une
  régression par la statistique. Rend un verdict **PASS / WARN / FAIL / INCONCLUSIVE** avec chacune
  de ses raisons, et un code de sortie par niveau.
- Contrôle chaque pull request dans la CI : le système testé du commit de base contre celui de la
  pull request, sur le même runner, dans l'ordre A-B-B-A ; le verdict fixe le statut du job.
- Restitue le verdict : résumé dans le job CI, JSON avec son schéma, JUnit XML, et une
  [page de tendances](https://bazanjeremy.github.io/loadlens/) alimentée par chaque exécution sur
  `main`.

Le dépôt embarque un système testé à régressions activables ([sut/README.md](sut/README.md)) : une
API de paiements (FastAPI + PostgreSQL) dont trois ralentissements (requêtes N+1, verrou, pool de
connexions) s'activent par variable d'environnement. Il sert à vérifier que le détecteur attrape de
vrais ralentissements.

## Démarrage rapide

Python 3.13 ou plus récent ; un environnement virtuel est recommandé.

```bash
git clone https://github.com/BazanJeremy/loadlens
cd loadlens
python -m pip install -e .
loadlens verdict --config config/slo.yaml --candidate fixtures/jmeter/2026-10-17-nominal-short.jtl
```

```text
loadlens verdict: PASS
  note: throughput of create_payment not checked: no target
  note: throughput of get_payment not checked: no target
  note: throughput of get_statement not checked: no target
  note: no baseline: SLO-only verdict, regressions not checked
```

Sur vos propres résultats :

```bash
# Contre une référence mesurée sur la même machine (au moins 10 fenêtres de 5 s par bras et par
# transaction, sinon INCONCLUSIVE)
loadlens verdict --config config/slo.yaml --baseline reference.jtl --candidate candidat.jtl
# Résultat LoadRunner DevWeb : SLO seuls ; ses horodatages ne portent pas de décalage UTC
loadlens verdict --config config/slo.yaml --candidate devWebDB.db --utc-offset +02:00
# Sorties pour d'autres outils et pour la CI
loadlens verdict --config config/slo.yaml --candidate candidat.jtl \
  --json verdict.json --junit verdict.xml --summary resume.md
```

Codes de sortie : 0 PASS, 1 WARN, 2 FAIL, 3 INCONCLUSIVE, 4 entrée inutilisable ; `--ci-status`
les convertit en statut de job CI. La chaîne complète (système testé sous `docker compose`, JMeter
en conteneur, protocole A-B-B-A de `load/abba.sh`) est décrite dans
[load/jmeter/README.md](load/jmeter/README.md) et [docs/verdict.md](docs/verdict.md).

## KPI et seuils

Valeurs par défaut de [`config/slo.yaml`](config/slo.yaml), déclarées et non mesurées. Chaque SLO
vaut pour chaque segment candidat, par transaction et pour l'ensemble. Définitions des KPI :
[docs/kpi.md](docs/kpi.md).

| KPI | SLO | Défaut | Franchi ⇒ |
|---|---|---|---|
| Latence p99 | dur | < 800 ms | FAIL |
| Taux d'erreur | dur | < 0,5 % | FAIL |
| Latence p95 | souple | < 300 ms | WARN |
| Apdex (T = 300 ms) | souple | ≥ 0,90 | WARN |
| Débit | souple | ≥ cible déclarée − 5 % | WARN |

**Régression**, seulement avec une référence, par transaction, sur le p95 de chaque fenêtre de
5 s : test de Mann-Whitney U unilatéral avec p < 0,05 ; variation du p95 supérieure à +10 % **et**
d'au moins 2 ms ; δ de Cliff d'au moins 0,147. Les trois conditions : FAIL ; deux sur trois : WARN.
Ces valeurs sont celles de la calibration ([docs/calibration.md](docs/calibration.md)).

**INCONCLUSIVE** : une comparaison demandée n'a pas pu se faire (référence sans échantillons bruts,
transaction sans échantillon réussi dans un bras, moins de 10 fenêtres dans un bras), ou rien n'a
été mesuré, cas qui fait aussi échouer le job CI. La stabilité du run (coefficient de variation)
est calculée mais n'est pas une raison d'INCONCLUSIVE : aucun instrument n'a passé la calibration.
Règles complètes : [docs/verdict.md](docs/verdict.md).

## Décisions

| ADR | Décision |
|---|---|
| [001](docs/adr/ADR-001-loadrunner-results-ingested-not-executed.md) | LoadRunner ne tourne jamais dans la CI : ses résultats, produits en local, sont commités comme fixtures datées puis ingérés |
| [002](docs/adr/ADR-002-common-result-schema.md) | Un schéma pivot, un adaptateur par outil ; un run porte soit des échantillons bruts, soit des agrégats par transaction ; une valeur inconnue reste inconnue |
| [003](docs/adr/ADR-003-abba-protocol-on-one-machine.md) | Référence et candidat mesurés dans le même job, sur la même machine, dans l'ordre A-B-B-A |
| [004](docs/adr/ADR-004-windowed-regression-detector.md) | Détecteur de régression sur des fenêtres de 5 s, taux de faux positifs publié tel que mesuré |
| [005](docs/adr/ADR-005-verdict-levels-and-ci-status.md) | Niveaux du verdict, leur ordre (FAIL, puis INCONCLUSIVE, puis WARN) et quand un job CI échoue |
| [006](docs/adr/ADR-006-absolute-floor-on-the-p95-change.md) | Plancher de 2 ms sur la variation du p95 : un pas d'une milliseconde ne fait plus FAIL |
| [007](docs/adr/ADR-007-verdict-outputs-and-trend-history.md) | Sorties du verdict (schéma JSON, correspondance JUnit) et historique des tendances sur `gh-pages` |

## Limites connues

- **Faux positifs : l'objectif de 5 % au plus n'est pas atteint.** Sur 120 exécutions saines (A/A)
  dans la CI, 2 finissent en FAIL, soit une borne supérieure de 5,15 % à 95 % de confiance
  ([ADR-006](docs/adr/ADR-006-absolute-floor-on-the-p95-change.md)).
- **Toutes les régressions ne sont pas attrapées** (même campagne) : N+1 détectée 10 fois sur 10,
  verrou 5 fois sur 10 ; la détection du pool de connexions (1 sur 10) n'est pas établie.
- **Bruit des runners partagés** : loadlens ne compare qu'une référence et un candidat mesurés dans
  le même job, sur la même machine ; la page de tendances montre les runs côte à côte sans les
  comparer. Les taux ci-dessus valent pour le profil de la calibration (4, 10 et 6 arrivées par
  seconde, palier de 60 s, runner `ubuntu-24.04` à 4 CPU) ; ailleurs, ils sont inconnus.
- **LoadRunner gratuit limité à 50 utilisateurs virtuels** (licence communautaire : un test à la
  fois, protocole DevWeb seul) ; ses binaires ne sont ni commités, ni téléchargés dans la CI.
- **Verdict DevWeb sur les SLO seuls** : une référence est refusée avec un résultat DevWeb, le
  détecteur n'ayant été calibré que sur des résultats JMeter.
- **Pas de protocole A-B-B-A ni de parité de verdict côté LoadRunner en v1** : la preuve « la
  régression N+1 finit en FAIL » n'existe que pour la chaîne JMeter
  ([load/loadrunner/README.md](load/loadrunner/README.md)).
- La licence OpenText interdit de publier des comparaisons détaillées avec d'autres outils :
  loadlens ne publie aucun chiffre JMeter et LoadRunner côte à côte.

## Documentation

[Système testé](sut/README.md) · [plan JMeter](load/jmeter/README.md) ·
[script DevWeb](load/loadrunner/README.md) · [KPI](docs/kpi.md) ·
[calibration](docs/calibration.md) · [verdict](docs/verdict.md) · [restitution](docs/reporting.md) ·
[bugs trouvés](docs/bug-evidence.md) · [CHANGELOG](CHANGELOG.md)

## Projets associés

Ces outils partagent les mêmes principes : **le déterministe d'abord, l'IA là où elle apporte — le QA reste l'arbitre.** Tous tournent en local, aucune clé API requise.

| Projet | Focus |
|---|---|
| [EvalForge](https://github.com/BazanJeremy/EvalForge) | Évaluation de LLM & calibration du juge |
| [ReleaseGuard](https://github.com/BazanJeremy/ReleaseGuard) | Verrou de release GO/NO-GO explicable |
| [FlakySense](https://github.com/BazanJeremy/flakysense) | Diagnostic statistique des tests flaky |
| [Anomaly Sentinel](https://github.com/BazanJeremy/anomaly-sentinel) | Tester les IA de détection d'anomalies (medtech · fintech) |
| [TestScribe](https://github.com/BazanJeremy/testscribe) | Enrichissement de bug reports assisté par IA |
| [SkyGuard](https://github.com/BazanJeremy/skyguard) | Quality gate sécurité pour systèmes critiques avioniques |
| [loadlens](https://github.com/BazanJeremy/loadlens) **← ce repo** | Verdict de performance argumenté sur des tests de charge |

## Licence

[MIT](LICENSE)
