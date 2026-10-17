# loadlens

**Verdict de performance argumenté à partir de résultats JMeter et LoadRunner : PASS / WARN / FAIL
fondé sur la statistique, pas sur un seuil isolé.**

[![CI](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml/badge.svg)](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-48%20passing-brightgreen?logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

> 🇬🇧 [English version](README.en.md)

> 🚧 **En construction.** Le moteur de verdict n'est pas encore livré : cette page décrit
> l'objectif de la v1. L'état réel est tenu dans le [CHANGELOG](CHANGELOG.md).

## Le problème

Un test de charge produit des milliers de mesures, mais la question « ce build est-il plus lent
que le précédent ? » se tranche souvent sur un seul chiffre comparé à un seuil, ou à l'œil sur un
graphique. Sur des machines cloud partagées, la variabilité d'une mesure de performance peut être
forte : [Laaber et al. (2019)](https://research.chalmers.se/publication/511491) ont mesuré des
coefficients de variation allant de 0,03 % à plus de 100 % selon les benchmarks et les instances.
Un seuil isolé bloque alors des changements sains, ou laisse passer une vraie régression.

## Ce que loadlens fera (v1)

- Exécuter un test de charge **Apache JMeter** dans la CI contre un système testé fourni avec le
  projet, dont les régressions sont activables.
- Ingérer les résultats d'**OpenText Performance Engineering for Developers** (ex-LoadRunner
  Developer, scripts DevWeb) produits en local.
- Ramener les deux à un schéma commun et calculer les KPI : percentiles de latence, taux d'erreur,
  débit, Apdex, stabilité.
- Comparer un run candidat à une référence exécutée sur la même machine, et rendre un verdict
  **PASS / WARN / FAIL / INCONCLUSIVE** avec ses raisons.
- Publier un résumé dans le job CI et une page de tendances.

## Statut

Livré : squelette et CI ; système testé (`sut/`) avec ses trois régressions activables — voir [sut/README.md](sut/README.md). Étape suivante : schéma commun, adaptateur JMeter et KPI.

## Licence

[MIT](LICENSE)
