# Calibration of the regression detectors

loadlens must say "this candidate is slower" only when it is, on CI runners whose own noise is of
the same order as the effects it looks for. Which statistical rule makes that call is measured
here, not assumed. The decision criteria below were written **before** the CI campaign ran.

## Protocol

- **A-B-B-A on one machine** (`load/abba.sh`): baseline segment A1, candidate B1, candidate B2,
  baseline A2. Before each segment the database is reloaded and the API recreated. Each segment
  is the CI JMeter profile: 10 s ramp (left out of the analysis), 60 s hold, 4 / 10 / 6 arrivals
  per second, fixed arrival-schedule seeds.
- **A/A runs** (`none`): the candidate is the baseline. Anything a detector flags is a false
  positive.
- **Regression runs**: the candidate runs with `SUT_REGRESSION_N_PLUS_ONE`, `_LOCK` or `_POOL`.
  A detection counts only on the transactions the regression is expected to slow down
  (`get_statement`, `create_payment`, any transaction respectively).
- **Runs are excluded, with the reason in the report**, when they did not finish or when a
  segment took more than 30 s of host wall clock beyond its schedule.
- **Analysis**: `python -m loadlens.calibration RUN_DIR...` (`src/loadlens/calibration.py`); in CI,
  the `Calibration` workflow (manual start) runs one job per run and analyzes them all.

## Detectors compared

All work per transaction on successful samples (`src/loadlens/compare.py`).

| Detector | Fires when |
|---|---|
| mission | one-sided Mann-Whitney p < 0.05 **and** relative Δp95 > +10% **and** Cliff's δ ≥ 0.147 |
| windowed | the same three conditions, the test and δ computed on 5 s window p95 values |
| bootstrap strict | 5th percentile of the moving-block bootstrap Δp95 > +10% |
| bootstrap | 5th percentile of the bootstrap Δp95 > 0 **and** Δp95 > +10% |

Single conditions are reported too, only to show which one carries the false positives.

**Self-check (candidate INCONCLUSIVE gate):** a run is *inconsistent* when the detector also
fires between its two baseline segments, A1 against A2, in either direction. Such a run would end
INCONCLUSIVE instead of PASS or FAIL. It is a data-driven alternative to the mission's
"CV < 15%" rule, which a healthy run already breaks (CV 0.32 to 0.47 measured on 2026-10-17,
`docs/kpi.md`).

## Decision criteria, declared before the CI campaign

1. A detector is **eligible** only if it detects N+1 in every N+1 run without making that run
   inconsistent — the N+1 FAIL is the central proof.
2. Its **false-positive rate** is reported with an exact one-sided 95% upper bound
   (Clopper-Pearson). "FPR ≤ 5%" can only be claimed with 0 flagged runs out of at least 59 A/A
   runs (upper bound 4.95%); with fewer runs the report states the bound reached, never "≤ 5%".
3. Among eligible detectors, the one that detects the most LOCK and POOL runs is chosen; on a
   tie, the mission detector.
4. The **self-check gate** is adopted only if it never makes an N+1 run inconsistent and makes
   at most 1 A/A run in 10 inconsistent. Otherwise the stability criterion stays open and goes
   back to the maintainer.

## Local pilot (2026-10-17) — not a result

Source: 5 runs on the development machine (`loadlens-work/calibration-local-2026-10-17`, not
committed): 12 CPUs, not the CI runner, so these figures only validate the pipeline.

| Detector | A/A flagged | A/A inconsistent | N+1 detected | LOCK detected |
|---|---|---|---|---|
| mission | 0/3 | 0/3 | 1/1 | 1/1 |
| windowed | 0/3 | 1/3 | 1/1 | 1/1 |
| bootstrap strict | 0/3 | 0/3 | 1/1 | 0/1 |
| bootstrap | 0/3 | 0/3 | 1/1 | 1/1 |

What the pilot already showed:

- **A single condition is not enough.** On healthy runs, Mann-Whitney alone gave p = 0.0054 for a
  Cliff's δ of 0.09, and Δp95 alone reached +12% when a p95 moved from 8 to 9 ms — the
  whole-millisecond resolution of a JTL.
- **Checking the candidate arm too was a mistake**: B1 against B2 made the N+1 run inconsistent,
  because two regressed segments differ from each other. The self-check now compares the baseline
  segments only.
- **N+1 also slowed the other transactions** (p95 +62% on `create_payment`, +43% on
  `get_payment`): they share the same API process.
- **LOCK was detected at 4 payments per second** (`create_payment` p95 +18%, δ = 0.48). At that
  rate the cause is more likely the extra SQL statement than lock contention — an inference, not
  measured.
- **One run was excluded**: the machine went to sleep during segment POOL-1/B2 (Windows System
  log: sleep at 15:27:47, resume at 19:59:30 local time). That segment's JTL only spanned 64 s, so
  JTL timestamps cannot reveal a suspended host; `load/abba.sh` now records each segment's host
  wall clock, and the analysis excludes a segment that ran far beyond its schedule.

## CI campaign

Not run yet. Its size and its runner depend on two open decisions: the repository's visibility
(GitHub's standard Linux runner has 2 CPUs and 8 GB for a private repository, 4 CPUs and 16 GB
for a public one, where minutes are also free — GitHub documentation, read on 2026-10-17) and the
number of A/A runs (at least 59 to claim FPR ≤ 5%).
