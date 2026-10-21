# ADR-007: Verdict outputs for other tools, and a trend history on gh-pages

- **Status:** Proposed
- **Date:** 2026-10-21
- **Deciders:** Jérémy Bazan

## Context

ADR-005 settled the verdict levels and the CI job status, and left the machine-readable verdict
(JSON schema, JUnit) to the reporting step. Before this step, `loadlens verdict --json` wrote the
level, the reasons, the notes and the comparisons, and no KPI (the `Verdict` model on `main` at
`8fb9c8d`): a job summary or a trend page had nothing to show but the level.

The maintainer decided on 2026-10-16 that the trend history is a JSON file on a `gh-pages` branch,
read by a static page, without a database. On 2026-10-20 he chose: the history takes the runs on
`main` only, pushes and manual runs; the CI workflow gets a manual trigger; in JUnit, WARN passes
and INCONCLUSIVE is skipped; the page draws its charts in SVG without a script; the schema is
generated from the model. On 2026-10-21 he chose one exception to the JUnit mapping, below.

Facts the decision rests on:

- GitHub Docs, "Configuring a publishing source for your GitHub Pages site" (read on 2026-10-20):
  "Commits pushed by a GitHub Actions workflow that uses the `GITHUB_TOKEN` do not trigger a
  GitHub Pages build."
- A JUnit test case has three ways not to pass: `<failure>`, `<error>` and `<skipped>`; there is
  no warning. ReleaseGuard, a release-decision tool that reads JUnit, counts `<failure>` and
  `<error>` as failed tests, leaves `<skipped>` out of the executed tests, and refuses a report
  without any executed test (`NoTestEvidenceError`). Source: its code at commit `2a6a97d`,
  `src/releaseguard/ingest/junit.py` and `src/releaseguard/evaluator.py`, read on 2026-10-20. No
  loadlens report has been run through it.
- The CI job fails on FAIL, and on an INCONCLUSIVE where nothing was measured (check
  `no_measurement`); WARN and any other INCONCLUSIVE leave it green (ADR-005).

## Decision

1. **Verdict JSON.** It carries a `schema_version` (1) and the KPIs of each candidate segment
   (`segments`). Its JSON schema (draft 2020-12) is generated from the model, committed in
   `schemas/verdict.schema.json`, and checked by a test against the model and against verdicts of
   every shape. The version is raised when a field is renamed, removed or changes meaning, not
   when one is added.
2. **JUnit mapping.** One test case per check target: the SLOs of a transaction in a candidate
   segment, the comparison of a transaction with the baseline. **A test case fails in JUnit
   exactly when its reasons fail the CI job:** FAIL is a `<failure>`; nothing measured is an
   `<error>` (the exception chosen on 2026-10-21: the check did not take place); any other
   INCONCLUSIVE is `<skipped>`; WARN passes, its reason in `<system-out>`.
3. **Trend history.** `history.json` on the `gh-pages` branch, one entry per run on `main` (level,
   overall KPIs of each candidate segment, commit, run link, time added); a run added again
   replaces its entry. The page is rebuilt from the whole history each time, plain HTML with
   inline SVG, and deployed by GitHub Pages through Actions. It shows runs side by side and
   compares nothing.

## Options Considered

1. **WARN as a JUnit `<failure>`** — a release tool would block on it while the CI job stays
   green: two answers for one verdict. Rejected.
2. **WARN as `<skipped>`** — the check was made; skipping it would take it out of the executed
   tests. Rejected.
3. **Nothing measured as `<skipped>`, like every INCONCLUSIVE** — what was first chosen. The
   report would then hold no failed test: ReleaseGuard refuses a report without executed test,
   but another reader can take "0 failures" for a pass, while the CI job is red. Replaced by
   `<error>` (decision 2).
4. **One test case per check (p99, error rate, Apdex, …)** — finer, but the verdict records the
   rules that broke, not each one that held: it would need a list of every check made. No reader
   needs it yet. Deferred.
5. **History in Actions artifacts** — they expire (14 days for this project's results). Rejected.
   **A database** — outside a static, free setup. Rejected.
6. **Publishing the page from the `gh-pages` branch** — a push with the `GITHUB_TOKEN` does not
   start the build (GitHub Docs, above); it would need a personal token stored as a secret.
   Rejected for a deployment through Actions; the branch keeps the history.
7. **A JavaScript chart library from a CDN** — a third-party script on the page, pinned or not.
   Rejected for SVG generated in Python: no script, the same bytes for the same history, testable
   as text.

## Consequences

- A tool that reads JUnit gets the same pass or fail as the CI job, and the JSON gives it the
  reasons and the KPIs, with a schema to check them against.
- The CI job summary shows the KPIs and the comparison, not only the level.
- The `trend page (main)` job runs on `main` only: pull requests never exercise it, its first run
  is the first push after merge. Its two git steps were run locally, twice, against a local bare
  repository with Git 2.54.0 (2026-10-20): the first run created `gh-pages`, the second added to
  it. The Git version of the CI runners is unknown; `git worktree add --orphan` needs 2.42 or later.
- The deployment needs GitHub Pages enabled with **GitHub Actions** as its source, a repository
  setting the maintainer sets. What the deployment step does without it has not been observed.
- The history grows by one entry per run on `main`, without a cap; its size over time is unknown.
- The time of an entry is when the run was added to the history, not when the load ran.
- A run with several candidate segments is drawn as its worst one; the runs of the history ran on
  different machines, so the page shows their latencies without comparing them (ADR-003).

## Sources

- GitHub Docs, "Configuring a publishing source for your GitHub Pages site",
  <https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site>,
  read on 2026-10-20.
- ReleaseGuard, commit `2a6a97d` (2026-10-12): `src/releaseguard/ingest/junit.py`
  (`parse_junit`), `src/releaseguard/evaluator.py` (`evaluate`), read on 2026-10-20.
- ADR-003 (A-B-B-A on one machine), ADR-005 (verdict levels and CI job status).
- JSON Schema draft 2020-12, <https://json-schema.org/draft/2020-12/schema>; the generated schema
  passes its meta-schema check (`jsonschema` 4.26.0, test `test_every_verdict_written_matches_the_schema`).
