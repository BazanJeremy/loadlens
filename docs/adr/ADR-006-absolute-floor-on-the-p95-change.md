# ADR-006: A 2 ms floor on the p95 change of the windowed detector

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** Jérémy Bazan

## Context

ADR-004 chose the windowed detector and named its weakness: under a p95 of 10 ms, a +10% change is
smaller than the one-millisecond resolution of a JTL, so the effect condition reduces to "one
millisecond more". Every false FAIL seen afterwards was such a step: `aa-51` in campaign
39058130424 (`get_statement` p95 6 → 7 ms) and `none-3` in `Evidence` run 39241955097
(`get_payment` 5 → 6 ms). These runs prompted a floor; they cannot serve as its evidence.

The value of the floor comes from the clock, not from data. JMeter 5.6.3 timestamps the start and
the end of a sample with `System.nanoTime() / 1000000` plus a fixed offset and records their
difference as the elapsed time, so truncation alone moves a p95 difference by less than 2 ms: it
can produce a one-millisecond step, never a two-millisecond one. A single value, 2 ms, and the
decision criteria were written in `docs/calibration.md` and merged (pull request #6, commit
`b926399`) before the campaign ran.

The campaign (`Calibration` run 39261296881 on `b926399`, 2026-10-19): 120 A/A runs and 10 runs
per switchable regression, 60 s hold, 4-CPU `ubuntu-24.04` runners, no run excluded, no job re-run.
The same runs give every detector of ADR-004 a new measurement on data that did not choose it.

| Detector | A/A runs flagged | FPR upper bound (95%) | A/A inconsistent | N+1 detected | LOCK detected | POOL detected |
|---|---|---|---|---|---|---|
| mission | 4/120 | 7.47% | 35/120 | 10/10 | 6/10 | 0/10 |
| windowed (ADR-004) | 8/120 | 11.71% | 26/120 | 10/10 | 5/10 | 2/10 |
| bootstrap strict | 0/120 | 2.47% | 10/120 | 10/10 | 2/10 | 0/10 |
| bootstrap | 0/120 | 2.47% | 12/120 | 10/10 | 5/10 | 0/10 |
| **windowed + 2 ms floor** | **2/120** | **5.15%** | **14/120** | **10/10** | **5/10** | **1/10** |

## Decision

1. **The effect condition of the windowed detector becomes: relative Δp95 above +10% and absolute
   Δp95 of at least 2 ms.** The Mann-Whitney U test, Cliff's δ, the 5 s windows and the "any
   transaction" rule stay those of ADR-004. With whole-millisecond p95 values, nothing changes
   from a baseline p95 of 10 ms upwards.
2. **Its false-positive rate is stated as measured**: 2 A/A runs flagged out of 120, exact
   one-sided 95% upper bound 5.15%. The 5% target is not demonstrated, and loadlens does not claim
   it.
3. **In the verdict, the floor is part of the effect condition**: a significant one-millisecond
   step meets two of the three conditions and ends WARN (weak regression), no longer FAIL.
4. **No self-check gate.** With the floored detector it makes 14 A/A runs out of 120 and 2 N+1
   runs inconsistent, above the declared limits (12 and 0). Run stability stays out of the reasons
   for INCONCLUSIVE, as in ADR-004.

This replaces the effect condition and the false-positive rate of ADR-004 (its decisions 1 and 2);
the rest of ADR-004 stands.

## Options Considered

1. **Keep ADR-004 unchanged** — on this campaign its detector flags 8 A/A runs out of 120, and 6 of
   them are no longer flagged with the floor. Not kept.
2. **Windowed with a 2 ms floor (chosen)** — the only change this campaign was declared to
   evaluate; it meets the eliminatory criterion, N+1 detected in every run.
3. **A floor above 2 ms** — not evaluated. On this campaign the two remaining A/A false positives
   and the five LOCK detections are all steps of exactly 2 ms, so a higher floor would have removed
   every LOCK detection along with them.
4. **The bootstrap detector** (5th percentile of the bootstrap Δp95 above 0, and Δp95 above +10%) —
   no A/A run flagged (upper bound 2.47%), N+1 10/10, LOCK 5/10, POOL 0/10. Its rule has not changed
   since ADR-004, so these are new measurements; but this campaign was declared to evaluate the
   floor, not to choose between detectors, and choosing it now would select on the data that
   measures it (the reason ADR-004 set aside its option 5). Not adopted; a campaign whose criteria
   are declared beforehand can settle it.
5. **Self-check gate with the floored detector** — rejected by the declared criterion (decision 4).

## Consequences

- N+1 ends FAIL in 10 runs out of 10: `get_statement` p95 from 6–9 ms to 33–55 ms.
- LOCK is detected in 5 runs out of 10, each a 2 ms step on `create_payment`. It is flagged far
  more often than a healthy candidate (5/10 against 2/120; one-sided Fisher exact test
  p = 1.7 × 10⁻⁵, a comparison not declared before the campaign).
- POOL is detected in 1 run out of 10, a rate not distinguishable from the A/A one (p = 0.22). This
  campaign does not establish that POOL is detected.
- On the A/A runs, the regression rules give 103 PASS, 15 WARN and 2 FAIL with the floor, against
  91, 21 and 8 without it (SLOs left out). WARN on a healthy candidate: 15 runs out of 120, upper
  bound 18.6%, measured and not tuned.
- The 1/60 of ADR-004 came from the campaign that chose the detector; on new data the same detector
  flags 8 runs out of 120. The two counts are compatible (two-sided Fisher exact test p = 0.28).
- The two remaining false positives: `aa-109` (`get_statement` 11 → 13 ms; all three transactions
  moved together between the arms although both run the same code, as in `aa-51`; cause unknown)
  and `aa-41` (`create_payment` 8 → 10 ms).
- A first start of the workflow (run 39253134923) was made on the commit before the criteria were
  merged; its plan step refused 120 A/A runs, so no load ran and no data exists.
- The floor holds for JMeter results, timed to the millisecond. For LoadRunner DevWeb results it
  is unknown until their timer resolution is checked.
- These figures hold for the CI profile (4, 10 and 6 arrivals per second, 60 s hold, 4-CPU
  `ubuntu-24.04` runner). On another machine or load profile they are unknown.

## Sources

- `docs/calibration.md`: the floor, the criteria declared before the campaign, the results.
- Calibration campaign: `Calibration` workflow run 39261296881 on commit `b926399`, 2026-10-19,
  report artifact `calibration-report` (`calibration.json`, SHA-256 `9260203c…a716`):
  https://github.com/BazanJeremy/loadlens/actions/runs/39261296881
- JMeter 5.6.3, `SampleResult.java` (`sampleNsClockInMs`, `setEndTime`), tag `rel/v5.6.3`:
  https://github.com/apache/jmeter/blob/rel/v5.6.3/src/core/src/main/java/org/apache/jmeter/samplers/SampleResult.java
- The same absolute-and-relative form in the Chromium performance dashboard, Catapult
  `dashboard/dashboard/find_change_points.py`, read on 2026-10-19.
- Implementation: `src/loadlens/calibration.py` (`FLOOR_MS`), `src/loadlens/verdict.py`,
  `config/slo.yaml`.
