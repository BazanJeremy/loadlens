# ADR-005: Verdict levels, their order, and when a CI job fails

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** Jérémy Bazan

## Context

`loadlens verdict` ends with one of four levels, decided when the project was planned on
2026-10-16: PASS, WARN, FAIL and INCONCLUSIVE, with exit codes 0 to 3. The same plan made WARN and
INCONCLUSIVE leave a CI job green, with a warning annotation. Three points were left open:

- **Which level wins** when a run has several reasons. Not specified.
- **What a missing baseline gives.** Two planned rules disagreed: a missing baseline ends
  INCONCLUSIVE, and a source that only exports aggregates falls back to SLOs alone.
- **What a run without any sample gives.** During development (2026-10-18, by hand, before any
  commit) an empty candidate run ended WARN, through its throughput targets; without targets it
  would have ended PASS with nothing checked.

Measured since: on the data of the first calibration campaign (run 39058130424), the regression
rules of the verdict end 56 A/A runs out of 60 PASS, 3 WARN and 1 FAIL; with the 2 ms floor of
ADR-006, on the second campaign (run 39261296881), 103 out of 120 PASS, 15 WARN and 2 FAIL
(`docs/verdict.md`). The first CI run of the verdict (run 39121427078, pull request #5) ended the
N+1 proof FAIL, `get_statement` p95 7 → 48 ms, and the gate PASS.

## Decision

1. **Levels and exit codes:** PASS 0, WARN 1, FAIL 2, INCONCLUSIVE 3; 4 for unusable input.
2. **Order:** the most severe reason sets the level, FAIL first, then INCONCLUSIVE, then WARN.
   Every reason is listed, whatever the level.
3. **Without a baseline,** the verdict rests on SLOs alone, and a note says so. INCONCLUSIVE
   means that a comparison was asked for and could not be made, or that nothing was measured.
4. **Nothing measured** (a candidate segment without any sample, or an A-B-B-A run that cannot be
   used) ends INCONCLUSIVE, never PASS, and **fails the CI job**. Any other WARN or INCONCLUSIVE
   leaves the job green, with a warning annotation. `loadlens verdict --ci-status` turns the
   verdict into that job status.
5. **Weak regression:** two of the three conditions of the detector (ADR-004, its effect condition
   amended by ADR-006) give WARN, the rule declared on 2026-10-16, before the first campaign. Its
   rate on A/A runs is published as measured, not tuned.
6. **Sample size:** fewer than 10 windows in an arm, for a transaction, ends INCONCLUSIVE. Declared
   on 2026-10-18, not calibrated; every comparison of the campaign had 24.

## Options Considered

1. **INCONCLUSIVE above FAIL** — rejected: an INCONCLUSIVE job stays green, so a broken hard SLO
   would pass the check. Argo Rollouts ranks the phases of an analysis the same way as the
   chosen order: Failed is worse than Error, which is worse than Inconclusive.
2. **A missing baseline always ends INCONCLUSIVE** — rejected: every single run, such as a push on
   `main`, would end with a warning, which teaches readers to ignore warnings.
3. **Nothing measured ends PASS** — rejected: a check that did not take place would read as a
   check that held.
4. **Nothing measured ends FAIL as a verdict** — Kayenta fails a canary when half of its metrics
   or more have no data. Not chosen for the verdict, which describes the candidate and has no
   finding against it; the CI job fails instead, which stops the merge the same way.
5. **No WARN for a weak regression until it is calibrated** — not chosen: the rule was declared
   before the campaign, and its measured rate is published.

## Consequences

- On the campaign profile, with the floor of ADR-006, a healthy candidate ends FAIL in 2 runs out
  of 120 (exact one-sided 95% upper bound 5.15%) and WARN in 15 out of 120 (upper bound 18.6%);
  before the floor, 1 out of 60 and 3 out of 60 on the first campaign. These figures come from the
  regression rules only: the campaign reports hold no KPIs, so their SLO outcomes are unknown.
- The verdict code (0 to 3) stays the level, for any consumer; only `--ci-status` maps it to a
  job status. The machine-readable verdict (JSON schema, JUnit) is settled with the reporting.
- The image check of the gate has only run with identical images: in run 39121427078, the four
  segments ran image `sha256:92092dbc…`, because the pull request did not change the system
  under test. How it behaves with two different images is not observed yet.

## Sources

- `docs/verdict.md`: rules, measured behaviour, CI jobs.
- Calibration campaigns: `Calibration` workflow runs 39058130424 (2026-10-17) and 39261296881
  (2026-10-19), report artifact `calibration-report`; the floor: ADR-006.
- First CI run of the verdict: CI run 39121427078, 2026-10-18, jobs `proof (N+1 must FAIL)` and
  `verdict gate (base vs pull request)`.
- Argo Rollouts, `utils/analysis/helpers.go` (`analysisStatusOrder`, `IsWorse`) and
  `analysis/analysis.go` (`assessRunStatus`), branch `master`, read 2026-10-19:
  https://github.com/argoproj/argo-rollouts
- Spinnaker, "How canary judgment works", NODATA rules, read 2026-10-19:
  https://spinnaker.io/docs/guides/user/canary/judge/
