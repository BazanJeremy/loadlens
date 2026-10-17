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
