# loadlens

**A reasoned performance verdict from JMeter and LoadRunner results: PASS / WARN / FAIL backed by
statistics, not by a single threshold.**

[![CI](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml/badge.svg)](https://github.com/BazanJeremy/loadlens/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-206%20passing-brightgreen?logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

> 🇫🇷 [Version française](README.md)

> 🚧 **Under construction.** The verdict and its CI check are delivered; reporting (job summary,
> trend page) and LoadRunner ingestion are not yet. The actual state is tracked in the
> [CHANGELOG](CHANGELOG.md).

## The problem

A load test produces thousands of measurements, yet the question "is this build slower than the
previous one?" is often settled on a single number compared to a threshold, or by eye on a chart.
On shared cloud machines, performance measurements can vary widely:
[Laaber et al. (2019)](https://research.chalmers.se/publication/511491) measured coefficients of
variation ranging from 0.03% to over 100% depending on the benchmark and the instance. A single
threshold then blocks healthy changes, or lets a real regression through.

## What loadlens will do (v1)

- Run an **Apache JMeter** load test in CI against a bundled system under test whose regressions
  can be switched on.
- Ingest results from **OpenText Performance Engineering for Developers** (formerly LoadRunner
  Developer, DevWeb scripts) produced locally.
- Normalize both into one common schema and compute KPIs: latency percentiles, error rate,
  throughput, Apdex, stability.
- Compare a candidate run against a baseline executed on the same machine, and emit a
  **PASS / WARN / FAIL / INCONCLUSIVE** verdict with its reasons.
- Publish a CI job summary and a trend page.

## Status

Delivered: skeleton and CI; system under test (`sut/`) with its three switchable regressions — see [sut/README.en.md](sut/README.en.md); common schema, JMeter JTL reading and KPI computation — see [docs/kpi.md](docs/kpi.md); JMeter load test run in CI — see [load/jmeter/README.en.md](load/jmeter/README.en.md); baseline versus candidate comparison, with its regression detector calibrated on the CI runners (2 false positives out of 120 healthy runs, N+1 regression caught in 10 runs out of 10) — see [docs/calibration.md](docs/calibration.md); PASS / WARN / FAIL / INCONCLUSIVE verdict with its reasons, and a CI check of every pull request (the system under test of the base commit against the pull request's, the verdict sets the job status), with the proof that the N+1 regression ends FAIL — see [docs/verdict.md](docs/verdict.md). Next: reporting (job summary, trend page, verdict as JSON and JUnit).

## License

[MIT](LICENSE)
