# ADR-004: Windowed regression detector, without a baseline self-check gate

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** Jérémy Bazan

## Context

The verdict needs a rule that says "this transaction is slower in the candidate". Four rules were
compared on A-B-B-A runs (ADR-003), against decision criteria written in `docs/calibration.md`
before the CI campaign ran. Two targets had been set on 2026-10-16: a false-positive rate of at
most 5%, and the N+1 regression detected. Run stability was to end a verdict INCONCLUSIVE, through
a "CV < 15%" rule that healthy runs already break (CV 0.32 to 0.47 measured on 2026-10-17,
`docs/kpi.md`).

The campaign (run 39058130424, 2026-10-17): 60 A/A runs and 5 runs per switchable regression,
60 s hold, 4-CPU `ubuntu-24.04` runners, no run excluded. A run counts as flagged when any of its
transactions is; *inconsistent* means the detector also fires between the two baseline segments.

| Detector | A/A runs flagged | FPR upper bound (95%) | A/A inconsistent | N+1 detected (inconsistent) | LOCK detected | POOL detected |
|---|---|---|---|---|---|---|
| mission | 2/60 | 10.1% | 14/60 | 5/5 (1) | 4/5 | 0/5 |
| windowed | 1/60 | 7.7% | 13/60 | 5/5 (0) | 3/5 | 2/5 |
| bootstrap strict | 1/60 | 7.7% | 4/60 | 5/5 (0) | 1/5 | 0/5 |
| bootstrap | 1/60 | 7.7% | 5/60 | 5/5 (0) | 3/5 | 0/5 |

## Decision

1. **Detector: windowed.** A transaction is regressed when all three conditions hold:
   - one-sided Mann-Whitney U test, candidate greater, on the p95 of each 5 s window (windows with
     at least 5 successful samples): p < 0.05;
   - relative change of the p95 of all successful samples of each arm: more than +10%;
   - Cliff's δ on the same window p95 values: at least 0.147.

   A candidate is regressed when any of its transactions is, the rule the false-positive rate
   above was measured with.
2. **Its false-positive rate is stated as measured**: 1 A/A run flagged out of 60, exact one-sided
   95% upper bound 7.7%. The 5% target is not demonstrated, and loadlens does not claim it.
3. **No baseline self-check gate.** Comparing A1 with A2 does not end a run INCONCLUSIVE, and run
   stability is not a reason for INCONCLUSIVE until an instrument passes a calibration whose
   criteria are declared beforehand. The other planned INCONCLUSIVE reasons, a missing baseline
   and too few samples, are not affected; they are defined with the verdict.

## Options Considered

1. **mission** (Mann-Whitney U, Δp95 and Cliff's δ on raw samples) — not eligible: in run
   `N_PLUS_ONE-5` it also fires between A1 and A2, so the central regression would end
   INCONCLUSIVE instead of FAIL.
2. **windowed (chosen)** — eligible; the most LOCK and POOL runs detected among eligible
   detectors (5 of 10), which is the declared choice criterion.
3. **bootstrap strict** (5th percentile of a moving-block bootstrap of Δp95 above +10%) —
   eligible; 1 LOCK or POOL run detected out of 10.
4. **bootstrap** (5th percentile above 0 and Δp95 above +10%) — eligible; 3 out of 10.
5. **Self-check gate with the windowed detector** — makes 13 of 60 A/A runs INCONCLUSIVE, above
   the declared limit of 1 in 10. It would also have turned the only false positive into
   INCONCLUSIVE (no A/A run flagged and consistent, upper bound 4.9%), but this combination was
   found after the results were known. Not adopted.
6. **60 more A/A runs** to tighten the bound — with 120 runs the bound falls under 5% only if no
   new false positive occurs; if the true rate is the observed 1/60, the chance of that is 36.5%.
   Not run.
7. **An absolute floor on the p95 change** — addresses the weakness described below, but a floor
   chosen now would be chosen on this campaign's data. Deferred to a new campaign.

## Consequences

- N+1 ends FAIL in 5 runs out of 5: `get_statement` p95 from 6–9 ms to 31–52 ms.
- LOCK was detected in 3 runs out of 5. This campaign does not establish that POOL is detected:
  its 2 detections are the same one-millisecond step as the only A/A false positive
  (`get_statement` p95 6 → 7 ms in `aa-51`, `POOL-3` and `POOL-4`).
- False FAIL on a healthy candidate: 1 run out of 60 observed, at most 7.7% at 95% confidence.
- Without a stability gate, nothing turns a disturbed run into INCONCLUSIVE yet: it ends PASS,
  WARN or FAIL like any other run.
- Known weakness: under a p95 of 10 ms, a +10% change is smaller than the one-millisecond
  resolution of a JTL, so the effect condition reduces to "one millisecond more" (already seen in
  the local pilot, `docs/calibration.md`).
- Follow-up: an absolute floor on the p95 change and a new stability instrument, each calibrated
  by a new CI campaign whose criteria are declared before it runs. The detector and its thresholds
  are never retuned on the data of the campaign that evaluates them.
- These figures hold for the CI profile (4, 10 and 6 arrivals per second, 60 s hold, 4-CPU
  `ubuntu-24.04` runner). On another machine or load profile they are unknown.

## Sources

- `docs/calibration.md`: protocol, detectors, criteria declared before the campaign, results.
- Calibration campaign: `Calibration` workflow run 39058130424 on commit `873e08a`, 2026-10-17,
  report artifact `calibration-report`:
  https://github.com/BazanJeremy/loadlens/actions/runs/39058130424
- Cliff's δ "small" boundary of 0.147: Romano et al. (2006), as cited in
  `src/loadlens/calibration.py`.
- Implementation: `src/loadlens/compare.py`, `src/loadlens/calibration.py` (Clopper-Pearson bound
  with `scipy.stats.beta`).
