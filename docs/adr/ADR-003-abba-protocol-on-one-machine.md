# ADR-003: Baseline and candidate measured A-B-B-A on one machine

- **Status:** Proposed
- **Date:** 2026-10-18
- **Deciders:** Jérémy Bazan

## Context

loadlens must tell whether a candidate build is slower than a baseline, on CI runners whose own
noise is of the same order as the effects it looks for:

- On shared cloud machines, the coefficient of variation of performance measurements ranged from
  0.03% to over 100% depending on the benchmark and the instance (Laaber et al., 2019).
- On this project's CI runners, healthy runs already vary widely: across the 60 A/A runs of the
  calibration campaign, the raw-latency CV per transaction and segment has a median of 0.270 and
  a maximum of 3.970 (`docs/calibration.md`, run 39058130424).
- How much the same build varies **between** two runners, or between two days, is unknown: this
  project has not measured it.

## Decision

A candidate is only compared with a baseline measured in the same job, on the same machine, in
the order A1, B1, B2, A2 (`load/abba.sh`). Before each segment the database is reloaded and the
API recreated; the ramp is left out of the analysis; the host wall clock of each segment is
recorded, and a run whose segment overran its schedule by more than 30 s is excluded with the
reason.

## Options Considered

1. **A-B-B-A on one machine (chosen)** — both arms share the runner, and their segments have the
   same mean position in time, so a drift that is linear over the job weighs on both arms
   equally (a property of the order, not a measurement). Costs four segments per comparison:
   5 min 33 s of job time for run `aa-1` of the calibration campaign.
2. **A then B on one machine** — half the segments, but any drift during the job is attributed
   to the candidate.
3. **Baseline taken from an earlier run on `main`** — no extra segment, but baseline and
   candidate come from different runners at different times, a noise this project has not
   measured.

## Consequences

- The verdict of a pull request needs the A-B-B-A job. A single run, such as a push on `main`,
  can be checked against SLOs and recorded in the history, not compared.
- The two baseline segments make an internal check possible: a detector should not fire between
  A1 and A2. As a stability gate this check was measured and not adopted (ADR-004).
- A-B-B-A does not remove all noise: in A/A run `aa-51` of the campaign, the three transactions
  moved together between the A and B arms although both arms ran the same code. Cause unknown.
- The calibration of ADR-004 holds for this protocol and the CI profile it was measured with
  (`docs/calibration.md`).

## Sources

- Laaber, Scheuner, Leitner (2019), "Software microbenchmarking in the cloud. How bad is it
  really?", Empirical Software Engineering: https://research.chalmers.se/publication/511491
- Calibration campaign, `Calibration` workflow run 39058130424 on commit `873e08a`, 2026-10-17:
  https://github.com/BazanJeremy/loadlens/actions/runs/39058130424 — results in
  `docs/calibration.md`.
- Protocol implementation: `load/abba.sh`, `src/loadlens/calibration.py`.
