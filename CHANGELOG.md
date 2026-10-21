# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Bugs are logged with what caught them, their cause and fix in
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
- Calibration results on the CI runners (60 A/A runs, 5 per regression) in `docs/calibration.md`:
  windowed detector retained, false positives 1/60 (95% upper bound 7.7%), N+1 detected in 5 runs
  out of 5, no stability gate. ADR-003 (A-B-B-A protocol on one machine) and ADR-004 (windowed
  regression detector), proposed.
- Verdict (`loadlens verdict`, `loadlens.verdict`): PASS / WARN / FAIL / INCONCLUSIVE with
  every reason, exit codes 0 to 3. Hard SLOs (p99, error rate) and soft SLOs (p95, Apdex,
  throughput against the declared rate) in every candidate segment; the windowed detector of
  ADR-004 when a baseline is given, two of its three conditions giving WARN; SLOs alone without
  a baseline. Rules and measured behaviour in `docs/verdict.md`.
- `config/slo.yaml`: the one place thresholds are written; a test checks that its regression
  values are the calibrated ones.
- CI: `gate` job on pull requests (system under test of the base commit against the pull
  request's, A-B-B-A, verdict sets the job status), `proof` job (N+1 switched on must end FAIL
  through a regression on `get_statement`), SLO verdict of the single run in the `jmeter` job.
  WARN and INCONCLUSIVE stay green with a warning annotation (`--annotations`).
- Manual `Evidence` workflow: A/A, N+1, LOCK and POOL runs through the verdict, outcomes listed
  in the job summary.
- `load/abba.sh`: `SUT_IMAGE_BASELINE` and `SUT_IMAGE_CANDIDATE` run a different image of the
  system under test in each arm; `meta.json` records the image each API container ran.
- Dependency: PyYAML 6.0.3.
- `loadlens verdict --ci-status`: exit with the CI job status instead of the verdict code. An
  INCONCLUSIVE where nothing was measured (a candidate segment without any sample, an unusable
  A-B-B-A run; check `no_measurement`) fails the job; any other INCONCLUSIVE and WARN stay green
  with a warning annotation. Used by the `jmeter` and `gate` jobs.
- ADR-005 (verdict levels, their order, and when a CI job fails), proposed.
- `docs/verdict.md`: throughput measured on the CI single run (3.99, 9.99 and 5.99 per second
  against floors of 3.8, 9.5 and 5.7), no POOL error on the CI runners, the signature of the
  local POOL errors (cause unknown), and the first `Evidence` run (3 runs per mode: N+1 FAIL
  3/3, LOCK 2/3, POOL 1/3, one A/A FAIL out of 3 on a one-millisecond step).
- Second calibration campaign declared before it runs (`docs/calibration.md`): the windowed
  detector with an absolute floor of 2 ms on the p95 change, the smallest change JMeter's
  millisecond clock cannot produce on its own; 120 A/A runs and 10 per regression; decision
  criteria for the floor and for a stability self-check. Results and decision: see Changed.
- `python -m loadlens.calibration`: the floored detector and its WARN rule, the list of
  transactions the floor removes with their p95 change, exact lower bounds of detection rates,
  `--expected-cpus` to exclude runs from another runner size. The `Calibration` workflow accepts up
  to 200 A/A runs and excludes runs without 4 CPUs.
- Second calibration campaign results in `docs/calibration.md` (run 39261296881: 120 A/A runs,
  10 per regression, none excluded), and ADR-006 (2 ms floor on the p95 change), proposed.
- Verdict JSON: `schema_version` (1) and `segments`, the KPIs of each candidate segment. Its JSON
  schema, generated from the model, is committed in `schemas/verdict.schema.json`
  (`loadlens schema` writes it; a test checks that the committed file is the generated one and
  that the verdicts written match it).
- `loadlens verdict --junit PATH`: JUnit XML report, one test case per transaction and segment for
  the SLOs and per transaction for the comparison. A test case fails when the verdict fails the
  CI job: FAIL is a `<failure>`, nothing measured an `<error>`, any other INCONCLUSIVE is
  `<skipped>`, WARN passes with its reason in `<system-out>`.
- `loadlens verdict --summary PATH`: Markdown summary appended to the file (level, reasons, KPIs
  of each candidate segment, comparison, what was not checked). The `jmeter`, `gate` and `proof`
  jobs write it to the job summary; `jmeter` and `gate` also keep the JUnit report.
- `loadlens trend`: adds a verdict to a JSON history (one entry per run, a run added again
  replaces its entry) and writes a static HTML page, p95 and error rate per run, without script or
  external resource.
- CI job `trend page (main)`, on `main` only: adds the `jmeter` job's verdict to `history.json`
  on the `gh-pages` branch and deploys the page with GitHub Pages. The CI workflow can be run by
  hand (`workflow_dispatch`).
- `docs/reporting.md` (the four outputs) and ADR-007 (verdict schema, JUnit mapping, trend
  history), proposed.
- LoadRunner DevWeb adapter (`loadlens.adapters.loadrunner_devweb.read_devweb`): reads the
  `Transactions` table of a `devWebDB.db`, built from real DevWeb 26.3 files only. A transaction's
  start is its end timestamp minus its duration; the caller gives the UTC offset, since the file
  carries none. Rows never observed (non-zero think time, another status) are refused with their
  row number. Format, evidence and fixtures in `fixtures/loadrunner/PROVENANCE.md`.
- `loadlens verdict --candidate` takes a `devWebDB.db` as well as a JTL (told apart by the SQLite
  file header), with `--utc-offset`. A DevWeb result gets an SLO-only verdict: a baseline is
  refused (exit code 4), the regression detector being calibrated on JMeter results only.
- DevWeb script of the three journeys (`load/loadrunner/`, closed model, 6 virtual users, 6 per
  second declared per transaction) and its local run instructions, licence limits (free edition:
  50 virtual users) and known limitations: no A-B-B-A protocol and no verdict parity on the
  LoadRunner side in v1.
- Fixtures (`fixtures/loadrunner/`), each with DevWeb's own summary: the format probe of
  2026-10-17 (120 transactions, half of them failed: the verdict is FAIL on the error rate) and a
  run of the script against the system under test on 2026-10-21 (1,161 transactions, all passed:
  the verdict is PASS, every SLO checked, throughput included). Tests check both files against
  DevWeb's summary, and that their timestamps mark the end of each transaction.

### Changed

- Regression detector: the effect condition also asks for a p95 change of at least 2 ms
  (`min_delta_p95_ms` in `config/slo.yaml`, ADR-006). Measured on the second campaign: false
  positives 2/120 (95% upper bound 5.15%, against 8/120 without the floor on the same runs), N+1
  detected in 10 runs out of 10, LOCK 5/10, POOL 1/10. A significant one-millisecond step now
  ends WARN instead of FAIL. The stability self-check failed its criterion again: run stability
  is still not a reason for INCONCLUSIVE.
- Two candidate segments with the same name are refused (exit code 4): a reason names its
  segment, and two alike made it ambiguous. With `--candidate`, the name is the file name.
- CI: a run on `main` is no longer cancelled by a newer one, since each is a point of the trend
  page; pull request runs still are.
- Development dependency: `jsonschema` 4.26.0, to check verdicts against their schema.
- Common schema: a sample's `response_code` may be `None`, when the source records no code per
  sample (DevWeb transactions).

### Fixed

- The JMeter container no longer waits 60 s after each test: JMeter 5.6.3's open model keeps idle
  non-daemon threads for a minute; `load/jmeter/entrypoint.sh` returns at `... end of run`
  (132 s instead of 192 s for the CI profile, JTL complete).
- Trend page: when every error rate was 0, the normal case, the error-rate axis read 0% to 400%.
  A chart whose values are all 0 now spans 1% (error rate) or 1 ms (p95); a chart with a value
  above 0 keeps the span of its data. Seen on the live page, not caught by a test
  ([bug evidence #1](docs/bug-evidence.md)).
