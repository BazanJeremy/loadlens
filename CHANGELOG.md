# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Bugs caught by the test suite are logged with their cause and fix in
[docs/bug-evidence.md](docs/bug-evidence.md).

## [Unreleased]

### Added

- Project skeleton: `src/` package, test suite, ADR template, bug evidence log.
- CI workflow: lint (ruff) and tests (`python -m pytest`) on Python 3.13.
- System under test (`sut/`): payments API (FastAPI + PostgreSQL) under `docker compose`, with
  `POST /payments`, `GET /payments/{id}`, a keyset-paginated `GET /accounts/{id}/statement`
  and `GET /health`.
- Deterministic seed (1,000 accounts, 5,000 merchants, 100,000 payments), reloaded on every
  `docker compose up`.
- Switchable regressions, off by default: `SUT_REGRESSION_N_PLUS_ONE`, `SUT_REGRESSION_LOCK`,
  `SUT_REGRESSION_POOL`. Hand measurements of their effect: `sut/README.en.md`.
- Functional test suite of the SUT, run in CI once per regression mode.
- Common result schema (`loadlens.schema.Run`): raw column-oriented samples **or**
  per-transaction aggregates, unknown values as `None` (ADR-002, proposed).
- JMeter JTL (CSV) adapter (`loadlens.adapters.jmeter.read_jtl`), reading columns by header
  name and rejecting malformed files with the offending line number.
- KPIs (`loadlens.kpi.compute`): nearest-rank p50/p90/p95/p99, error rate, throughput, Apdex,
  CV, overall and per transaction; definitions in `docs/kpi.md`.
- JMeter 5.6.3 runner image (`load/jmeter/Dockerfile`, archive checksum verified) and a first
  open-model plan (`load/jmeter/loadlens.jmx`), used to record real JTL fixtures
  (`fixtures/jmeter/`, provenance in `PROVENANCE.md`).
- ADR-001 (LoadRunner results ingested, not executed, in CI), proposed.
- `loadlens kpi` command (also `python -m loadlens`): KPIs of a JTL as JSON, with run metadata
  (tool version, load profile, machine) and `--warmup-s` to leave out the ramp. Exit code 4 for
  unusable input; 1 to 3 are reserved for verdicts.
- CI job `jmeter (short profile)`: SUT in containers, JMeter 5.6.3 in CLI mode (10 s ramp,
  120 s hold), KPIs computed from the JTL, JTL, log and KPIs kept as artifacts for 14 days.
- JMeter plan documentation (`load/jmeter/README.en.md`): parameters, best practices applied,
  first local measurement of the CI profile.
- Baseline versus candidate comparison (`loadlens.compare`): one-sided Mann-Whitney U, exact
  Cliff's delta, relative Δp95, the same tests on 5 s window p95 values, and a moving-block
  bootstrap interval of Δp95, per transaction.
- A-B-B-A protocol on one machine (`load/abba.sh`): database reloaded and API recreated before
  each segment, host wall clock recorded per segment.
- Detector calibration (`python -m loadlens.calibration`, manual `Calibration` workflow): false
  positives on A/A runs with an exact 95% upper bound, power per regression, baseline self-check,
  runs excluded with their reason. Protocol and pre-declared criteria in `docs/calibration.md`.

### Fixed

- The JMeter container no longer waits 60 s after each test: JMeter 5.6.3's open model keeps idle
  non-daemon threads for a minute; `load/jmeter/entrypoint.sh` returns at `... end of run`
  (132 s instead of 192 s for the CI profile, JTL complete).
