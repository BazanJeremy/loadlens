# loadlens

**A reasoned performance verdict from JMeter and LoadRunner results: PASS / WARN / FAIL backed by
statistics, not by a single threshold.**

[![CI](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml/badge.svg)](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-267%20passing-brightgreen?logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

> 🇫🇷 [Version française](README.md)

## The problem

A load test produces thousands of measurements, yet the question "is this build slower than the
previous one?" is often settled on a single number compared to a threshold, or by eye on a chart.
On shared cloud machines, performance measurements can vary widely:
[Laaber et al. (2019)](https://research.chalmers.se/publication/511491) measured coefficients of
variation ranging from 0.03% to over 100% depending on the benchmark and the instance. A single
threshold then blocks healthy changes, or lets a real regression through.

## What loadlens does

- Reads results from **Apache JMeter** (CSV JTL files) and **OpenText Performance Engineering for
  Developers** (formerly LoadRunner Developer: the `devWebDB.db` of the DevWeb protocol), and
  normalizes them into one common schema.
- Computes KPIs: latency percentiles, error rate, throughput, Apdex, coefficient of variation, per
  transaction and overall.
- Checks SLOs and, when a baseline measured on the same machine is given, looks for a regression
  with statistics. Emits a **PASS / WARN / FAIL / INCONCLUSIVE** verdict with every one of its
  reasons, and one exit code per level.
- Checks every pull request in CI: the system under test of the base commit against the pull
  request's, on the same runner, in A-B-B-A order; the verdict sets the job status.
- Reports the verdict: a CI job summary, JSON with its schema, JUnit XML, and a
  [trend page](https://bazanjeremy.github.io/loadlens/) fed by every run on `main`.

The repository ships a system under test with switchable regressions
([sut/README.en.md](sut/README.en.md)): a payments API (FastAPI + PostgreSQL) whose three
slowdowns (N+1 queries, a lock, a connection pool) are switched on by environment variables. It is
there to check that the detector catches real slowdowns.

## Quick start

Python 3.13 or later; a virtual environment is recommended.

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

On your own results:

```bash
# Against a baseline measured on the same machine (at least 10 windows of 5 s per arm and per
# transaction, otherwise INCONCLUSIVE)
loadlens verdict --config config/slo.yaml --baseline baseline.jtl --candidate candidate.jtl
# LoadRunner DevWeb result: SLOs only; its timestamps carry no UTC offset
loadlens verdict --config config/slo.yaml --candidate devWebDB.db --utc-offset +02:00
# Outputs for other tools and for CI
loadlens verdict --config config/slo.yaml --candidate candidate.jtl \
  --json verdict.json --junit verdict.xml --summary summary.md
```

Exit codes: 0 PASS, 1 WARN, 2 FAIL, 3 INCONCLUSIVE, 4 unusable input; `--ci-status` turns them
into a CI job status. The full chain (system under test under `docker compose`, JMeter in a
container, the A-B-B-A protocol of `load/abba.sh`) is described in
[load/jmeter/README.en.md](load/jmeter/README.en.md) and [docs/verdict.md](docs/verdict.md).

## KPIs and thresholds

Defaults of [`config/slo.yaml`](config/slo.yaml), declared, not measured. Each SLO holds for every
candidate segment, per transaction and overall. KPI definitions: [docs/kpi.md](docs/kpi.md).

| KPI | SLO | Default | Broken ⇒ |
|---|---|---|---|
| p99 latency | hard | < 800 ms | FAIL |
| Error rate | hard | < 0.5% | FAIL |
| p95 latency | soft | < 300 ms | WARN |
| Apdex (T = 300 ms) | soft | ≥ 0.90 | WARN |
| Throughput | soft | ≥ declared target − 5% | WARN |

**Regression**, only with a baseline, per transaction, on the p95 of each 5 s window: one-sided
Mann-Whitney U test with p < 0.05; p95 change above +10% **and** at least 2 ms; Cliff's δ of at
least 0.147. All three conditions: FAIL; two of three: WARN. These are the calibrated values
([docs/calibration.md](docs/calibration.md)).

**INCONCLUSIVE**: a comparison was asked for and could not be made (a baseline without raw
samples, a transaction without any successful sample in an arm, fewer than 10 windows in an arm),
or nothing was measured, which also fails the CI job. Run stability (coefficient of variation) is
computed but is not a reason for INCONCLUSIVE: no instrument has passed calibration. Full rules:
[docs/verdict.md](docs/verdict.md).

## Decisions

| ADR | Decision |
|---|---|
| [001](docs/adr/ADR-001-loadrunner-results-ingested-not-executed.md) | LoadRunner never runs in CI: its results, produced locally, are committed as dated fixtures and ingested |
| [002](docs/adr/ADR-002-common-result-schema.md) | One pivot schema, one adapter per tool; a run carries either raw samples or per-transaction aggregates; an unknown value stays unknown |
| [003](docs/adr/ADR-003-abba-protocol-on-one-machine.md) | Baseline and candidate measured in the same job, on the same machine, in A-B-B-A order |
| [004](docs/adr/ADR-004-windowed-regression-detector.md) | Regression detector on 5 s windows, its false-positive rate published as measured |
| [005](docs/adr/ADR-005-verdict-levels-and-ci-status.md) | Verdict levels, their order (FAIL, then INCONCLUSIVE, then WARN) and when a CI job fails |
| [006](docs/adr/ADR-006-absolute-floor-on-the-p95-change.md) | A 2 ms floor on the p95 change: a one-millisecond step no longer ends FAIL |
| [007](docs/adr/ADR-007-verdict-outputs-and-trend-history.md) | Verdict outputs (JSON schema, JUnit mapping) and the trend history on `gh-pages` |

## Known limitations

- **False positives: the target of at most 5% is not met.** Out of 120 healthy (A/A) runs in CI,
  2 end FAIL, an upper bound of 5.15% at 95% confidence
  ([ADR-006](docs/adr/ADR-006-absolute-floor-on-the-p95-change.md)).
- **Not every regression is caught** (same campaign): N+1 detected 10 times out of 10, the lock 5
  times out of 10; detection of the connection pool (1 out of 10) is not established.
- **Shared-runner noise**: loadlens only compares a baseline and a candidate measured in the same
  job, on the same machine; the trend page shows runs side by side without comparing them. The
  rates above hold for the calibration profile (4, 10 and 6 arrivals per second, 60 s hold, 4-CPU
  `ubuntu-24.04` runner); elsewhere they are unknown.
- **Free LoadRunner edition limited to 50 virtual users** (community licence: one test at a time,
  DevWeb protocol only); its binaries are never committed or downloaded in CI.
- **DevWeb verdict on SLOs alone**: a baseline is refused with a DevWeb result, the detector having
  been calibrated on JMeter results only.
- **No A-B-B-A protocol and no verdict parity on the LoadRunner side in v1**: the proof that the
  N+1 regression ends FAIL exists for the JMeter chain only
  ([load/loadrunner/README.en.md](load/loadrunner/README.en.md)).
- The OpenText licence forbids publishing detailed comparisons with other tools: loadlens publishes
  no JMeter and LoadRunner figures side by side.

## Documentation

[System under test](sut/README.en.md) · [JMeter plan](load/jmeter/README.en.md) ·
[DevWeb script](load/loadrunner/README.en.md) · [KPIs](docs/kpi.md) ·
[calibration](docs/calibration.md) · [verdict](docs/verdict.md) · [reporting](docs/reporting.md) ·
[bugs found](docs/bug-evidence.md) · [CHANGELOG](CHANGELOG.md)

## Related projects

These tools share the same principles: **deterministic first, AI where it earns its place — the QA stays the arbiter.** All run locally, no API keys required.

| Project | Focus |
|---|---|
| [EvalForge](https://github.com/BazanJeremy/EvalForge) | LLM evaluation & judge calibration |
| [ReleaseGuard](https://github.com/BazanJeremy/ReleaseGuard) | Explainable GO/NO-GO release gate |
| [FlakySense](https://github.com/BazanJeremy/flakysense) | Statistical flaky-test diagnosis |
| [Anomaly Sentinel](https://github.com/BazanJeremy/anomaly-sentinel) | Testing AI anomaly-detection systems (medtech · fintech) |
| [TestScribe](https://github.com/BazanJeremy/testscribe) | AI-assisted bug report enrichment |
| [SkyGuard](https://github.com/BazanJeremy/skyguard) | Security quality gate for critical avionics systems |
| [loadlens](https://github.com/BazanJeremy/loadlens) **← this repo** | Reasoned performance verdict from load tests |

## License

[MIT](LICENSE)
