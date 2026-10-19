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

## CI campaign (2026-10-17)

Source: `Calibration` workflow, run
[39058130424](https://github.com/BazanJeremy/loadlens/actions/runs/39058130424) on commit
`873e08a`, 77 jobs out of 77 successful; figures from its `calibration-report` artifact
(`calibration.json`), read on 2026-10-18. 60 A/A runs and 5 runs per regression, 60 s hold. All 75
runs ran on 4-CPU `ubuntu-24.04` runners (`cpu_count` recorded in every run; the repository is
public). No run was excluded.

| Detector | A/A runs flagged | FPR upper bound (95%) | A/A inconsistent | N+1 detected (inconsistent) | LOCK detected (inconsistent) | POOL detected (inconsistent) |
|---|---|---|---|---|---|---|
| mission | 2/60 | 10.1% | 14/60 | 5/5 (1) | 4/5 (2) | 0/5 (2) |
| windowed | 1/60 | 7.7% | 13/60 | 5/5 (0) | 3/5 (0) | 2/5 (0) |
| bootstrap strict | 1/60 | 7.7% | 4/60 | 5/5 (0) | 1/5 (0) | 0/5 (0) |
| bootstrap | 1/60 | 7.7% | 5/60 | 5/5 (0) | 3/5 (0) | 0/5 (0) |

### The declared criteria, applied as written

1. **Eligible: windowed, bootstrap strict and bootstrap.** The mission detector is not: in run
   `N_PLUS_ONE-5` it also fires between the two baseline segments, so that run would end
   INCONCLUSIVE instead of FAIL.
2. **No detector can claim "FPR ≤ 5%".** None reached 0 flagged A/A runs; the lowest count is
   1/60, an upper bound of 7.7%.
3. **Chosen: windowed**, with 5 LOCK and POOL runs detected out of 10, against 3 for bootstrap and
   1 for bootstrap strict.
4. **The self-check gate is not adopted.** With the windowed detector it makes 13 A/A runs out of
   60 inconsistent, above the declared limit of 1 in 10. The stability criterion stays open and
   goes back to the maintainer.

**Decision (maintainer, 2026-10-18):** the windowed detector, its false-positive rate stated as
measured (1/60, upper bound 7.7%), and no self-check gate: run stability is not a reason for
INCONCLUSIVE until an instrument passes a calibration declared beforehand. Rationale and options:
[ADR-004](adr/ADR-004-windowed-regression-detector.md); protocol:
[ADR-003](adr/ADR-003-abba-protocol-on-one-machine.md).

### What else the campaign shows

- **N+1 stands out in every run**: `get_statement` p95 goes from 6–9 ms to 31–52 ms (+417% to
  +550%), with a raw Cliff's δ of 0.998 or more in all five runs.
- **LOCK raises the `create_payment` p95 by +12% to +22%** in four runs out of five. In `LOCK-4`
  the candidate p95 is lower (12 → 8 ms); cause unknown.
- **The windowed detector's only false positive and its two POOL detections are the same
  one-millisecond step**: `get_statement` p95 6 → 7 ms (+17%) in `aa-51`, `POOL-3` and `POOL-4`.
  This campaign therefore does not establish that POOL is detected. Without those two runs,
  windowed and bootstrap would tie on LOCK (3/5 each), and the declared tie-break, the mission
  detector, would not settle it: mission is not eligible.
- **In `aa-51`, all three transactions moved together** between the A and B arms (raw Cliff's δ
  +0.217 to +0.261), although both arms run the same code. Cause unknown.
- **The bootstrap false positive** (`aa-15`) is a `create_payment` p95 of 7 → 12 ms (+71%) with a
  raw Cliff's δ of +0.061.
- **A/A stability**, per transaction and segment: raw-latency CV median 0.270, 95th percentile
  1.031, max 3.970; CV of the 5 s window p95 median 0.175, max 2.032.

## Second campaign: an absolute floor (criteria declared on 2026-10-19, before it runs)

ADR-004 names the windowed detector's weakness: under a p95 of 10 ms, a +10% change is smaller
than one millisecond, so the effect condition reduces to "one millisecond more". Every false FAIL
seen since is such a step: `aa-51` above, and `none-3` in `Evidence` run 39241955097
(`get_payment` p95 5 → 6 ms). So are the POOL detections (`POOL-3` and `POOL-4` above, `POOL-2` in
that run). These runs prompted the floor, and any floor of 2 ms or more removes them by
construction: **they cannot serve as its evidence.** Only this campaign does.

### The floor, and why 2 ms

The effect condition becomes: relative Δp95 above +10% **and** absolute Δp95 of at least 2 ms.
The other two conditions do not change. With whole-millisecond p95 values, the floor changes
nothing from a baseline p95 of 10 ms upwards, where more than +10% already means at least 2 ms:
it only acts where the weakness is.

The value comes from the clock, not from data. JMeter 5.6.3 timestamps the start and the end of a
sample with `System.nanoTime() / 1000000` plus a fixed offset, and records their difference as the
elapsed time (`SampleResult.java`, tag `rel/v5.6.3`). Each truncation is off by less than 1 ms, so
each elapsed time is less than 1 ms away from the duration the clock measured. So is each p95, an
order statistic moving less than the values it is taken from, and a difference of two p95 values
is less than 2 ms away from the true one. Truncation alone can therefore produce a one-millisecond
step, never a two-millisecond one: **2 ms is the smallest floor the clock cannot reach on its
own.** A 2 ms step shows that the p95 rose, not by how much. One value is declared and no other
is tried, so no floor is selected on this campaign's data.

Prior use of the same form: the Chromium performance dashboard rejects a change point when either
the absolute or the relative change of the median is under its threshold
([`find_change_points.py`](https://chromium.googlesource.com/catapult.git/+/refs/heads/main/dashboard/dashboard/find_change_points.py)).

### Protocol and detectors

As in the first campaign (A-B-B-A, CI profile, 60 s hold, `ubuntu-24.04` runners), in **one**
run of the `Calibration` workflow, on the commit that merges this section: **120 A/A runs and 10
per regression**, 150 jobs. With 120 A/A runs, "≤ 5%" can be claimed with at most one flagged
run (upper bound 3.9%); N+1 detected in 10 runs out of 10 gives a one-sided 95% lower bound of
74%.

Reported by `src/loadlens/calibration.py`, on the same runs:

- **windowed** (ADR-004, unchanged): a new measure of the detector in use, on data that did not
  choose it;
- **windowed + floor**;
- **windowed + floor, at least 2 of its 3 conditions**: the verdict's WARN rule with the floor.

### Decision criteria, declared before the second campaign

1. The floor is adopted only if windowed + floor flags `get_statement` in **every** N+1 run.
2. Its false-positive rate is reported with the exact one-sided 95% upper bound; "≤ 5%" is claimed
   only if that bound is under 5%. The target of 2026-10-16 (false-positive rate ≤ 5% and N+1
   detected) is met only if criteria 1 and 2 both hold.
3. LOCK and POOL detections are reported with an exact one-sided 95% lower bound. They are not a
   condition: a one-millisecond detection was no evidence. Every transaction the floor removes,
   in any run, is listed with its p95 change.
4. In the verdict, the floor joins the effect condition: a significant one-millisecond step meets
   two conditions out of three and ends WARN. On A/A runs, the rate of this WARN (runs flagged
   with at least 2 of the 3 conditions, not with all 3) is measured and reported, not tuned. SLOs
   are not part of it.
5. **Stability instrument:** the self-check with windowed + floor (A1 against A2, both ways). It
   becomes a reason for INCONCLUSIVE only if it makes no N+1 run inconsistent and at most 1 A/A
   run in 10 (12 of 120): the criterion of the first campaign, unchanged.
6. Runs are excluded as in the first campaign, and also when their `cpu_count` is not 4
   (`--expected-cpus 4`).
7. One execution: no job is re-run. If more than 10% of the runs are excluded, the campaign is
   void and the decision goes back to the maintainer.
8. The campaign is not pooled with run 39058130424 or 39241955097.

The floor holds for JMeter results, timed to the millisecond. The timer resolution of LoadRunner
DevWeb results is unknown; it is checked when their adapter is written.
