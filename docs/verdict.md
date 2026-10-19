# Verdict

`loadlens verdict` tells whether a candidate is fit to ship, with its reasons: **PASS**,
**WARN**, **FAIL** or **INCONCLUSIVE**. It checks the candidate against SLOs and, when a baseline
measured on the same machine is given, looks for a regression with the detector of ADR-004, its
effect condition amended by ADR-006.
Thresholds live in one file, [`config/slo.yaml`](../config/slo.yaml).

```bash
# A-B-B-A run (load/abba.sh): meta.json gives the segments, the warm-up and the target rates
loadlens verdict --config config/slo.yaml --abba results/run --json verdict.json

# Single run, SLOs only
loadlens verdict --config config/slo.yaml --candidate run.jtl --warmup-s 10 \
  --target-rps create_payment=4 --target-rps get_payment=10 --target-rps get_statement=6
```

`--baseline JTL` (repeatable) adds a comparison to the second form. `--annotations` also prints
a GitHub Actions annotation.

## Levels

| Level | Exit code | Meaning |
|---|---|---|
| PASS | 0 | every check that could be made held |
| WARN | 1 | a soft SLO is broken, or a weak regression is found |
| FAIL | 2 | a hard SLO is broken, or a regression is found |
| INCONCLUSIVE | 3 | a check could not be made: see below |
| — | 4 | unusable input (missing or malformed file, invalid argument) |

The most severe reason sets the level, in this order: **FAIL, INCONCLUSIVE, WARN**. FAIL ranks
first because a broken hard SLO or a detected regression holds whatever else could not be
checked, and an INCONCLUSIVE CI job stays green: ranked above FAIL, it would let a broken p99
through. Every reason is listed, whatever the level; what was not checked is listed as a note.

## SLOs

| SLO | Kind | Default | Broken when |
|---|---|---|---|
| p99 latency | hard | 800 ms | p99 ≥ 800 ms |
| Error rate | hard | 0.5% | error rate ≥ 0.5% |
| p95 latency | soft | 300 ms | p95 ≥ 300 ms |
| Apdex (T = 300 ms) | soft | 0.90 | Apdex < 0.90 |
| Throughput | soft | target − 5% | achieved rate < target × 0.95 |

These defaults are declared, not measured. Each SLO is checked in **every candidate segment**,
for each transaction and for all transactions together, with the KPI definitions of
[`kpi.md`](kpi.md) (warm-up left out). Throughput is checked per transaction, against the rate
the load profile declares; a transaction without a declared rate is not checked, and a
transaction with a declared rate but no sample breaks the SLO (0 per second). A KPI that is
unknown, such as the Apdex of a source that only exports aggregates, is listed as not checked,
never as met. A segment without any sample ends the verdict INCONCLUSIVE: nothing in it can be
said to hold.

## Regression

Only when a baseline is given. Per transaction, with the windowed detector of
[ADR-004](adr/ADR-004-windowed-regression-detector.md):

1. one-sided Mann-Whitney U test, candidate greater, on the p95 of each 5 s window: p < 0.05;
2. change of the p95 of all successful samples of each arm: more than +10% **and** at least
   2 ms ([ADR-006](adr/ADR-006-absolute-floor-on-the-p95-change.md)): under a p95 of 10 ms,
   +10% is less than one step of the millisecond clock JMeter times samples with;
3. Cliff's δ on the same window p95 values: at least 0.147.

All three: **FAIL** (regression). Two of three: **WARN** (weak regression), a rule declared on
2026-10-16, before the calibration campaign, and kept as declared. Its rate was measured
afterwards (below), not tuned. A significant one-millisecond step meets two conditions: WARN at
most.

The first six values of `regression:` in `config/slo.yaml` are the calibrated ones; a test
checks that they match the detector the campaigns measured. Changed, they leave the measured
false-positive rate without a source.

## INCONCLUSIVE

A comparison was asked for and could not be made:

- no baseline run, or a run without raw samples (aggregates cannot be compared);
- a transaction without any successful sample in one of the arms;
- fewer than 10 windows in an arm, for a transaction (`min_windows_per_arm`, declared on
  2026-10-18, not calibrated; every comparison of the calibration campaign had 24);
- an A-B-B-A run that cannot be used, for instance a segment that overran its schedule by more
  than 30 s ([ADR-003](adr/ADR-003-abba-protocol-on-one-machine.md)).

A candidate segment without any sample is INCONCLUSIVE too, baseline or not. Run stability is
not a reason: no instrument has passed a calibration yet (ADR-004, and again ADR-006). Without a baseline, the
verdict rests on SLOs alone and a note says that regressions were not checked.

## Measured behaviour

**Regression rules on the second calibration campaign** (run 39261296881, 2026-10-19, 120 A/A
runs and 10 per regression, 4-CPU `ubuntu-24.04` runners, 60 s hold). The campaign report holds
the per-transaction comparisons, not the KPIs, so this applies the regression rules of
`src/loadlens/verdict.py` and `config/slo.yaml` only, without the SLOs:

| Runs | PASS | WARN | FAIL |
|---|---|---|---|
| A/A (120) | 103 | 15 | 2 |
| N+1 (10) | 0 | 0 | 10 |
| LOCK (10) | 1 | 4 | 5 |
| POOL (10) | 7 | 2 | 1 |

- A healthy candidate ends FAIL in 2 runs out of 120 (exact one-sided 95% upper bound 5.15%) and
  WARN in 15 (upper bound 18.6%); not PASS in 17 out of 120 (upper bound 20.5%).
- Without the floor, the same A/A runs give 91 PASS, 21 WARN and 8 FAIL, and the POOL runs 6, 2
  and 2; N+1 and LOCK do not change.
- The FAIL counts are those of ADR-006. The single POOL FAIL is a rate not distinguishable from
  the A/A one: this campaign does not establish that POOL is detected.

**Regression rules on the first calibration campaign, before the floor** (run 39058130424,
2026-10-17, 4-CPU `ubuntu-24.04` runners, 60 s hold), regression rules only:

| Runs | PASS | WARN | FAIL |
|---|---|---|---|
| A/A (60) | 56 | 3 | 1 |
| N+1 (5) | 0 | 0 | 5 |
| LOCK (5) | 1 | 1 | 3 |
| POOL (5) | 2 | 1 | 2 |

- A healthy candidate ends FAIL in 1 run out of 60 (exact one-sided 95% upper bound 7.7%) and
  WARN in 3 out of 60 (upper bound 12.4%); not PASS in 4 out of 60 (upper bound 14.6%).
- The FAIL counts are those of ADR-004, recomputed independently from the same report.
- The 2 POOL FAILs are the same one-millisecond step as the only A/A FAIL (ADR-004): this
  campaign does not establish that POOL is detected.

**Full verdict on the local pilot** (2026-10-17, one A-B-B-A run each, on a local machine with 12
CPUs according to `meta.json`, same profile; runs not committed): the 3 A/A runs PASS; N+1 and LOCK FAIL through a
regression; POOL FAIL through the error rate, 16.5% in segment B2 and under 0.5% in B1. Cause
unknown.

**Throughput on the CI single run** (10 s ramp, 120 s hold): unknown. The arrival schedules use
fixed seeds, so the count of arrivals in the analysed window is the same from run to run: if it
falls under target − 5%, every run of that profile warns. The local pilot (60 s hold) does not.

## In CI

- **Pull requests, `gate` job:** the system under test of the base commit (A) against the pull
  request's (B), A-B-B-A on one runner. Both arms use the pull request's `compose.yaml` and
  JMeter plan; a step checks that each segment ran its arm's image. FAIL fails the job.
- **Pull requests, `proof` job:** an A-B-B-A run with N+1 switched on in B. The job passes only
  if the verdict is FAIL with a regression on `get_statement`.
- **Every push and pull request, `jmeter` job:** the single run, SLOs only.
- WARN and INCONCLUSIVE leave the job green, with a warning annotation; FAIL turns it red.
- **Manual `Evidence` workflow:** runs A/A, N+1, LOCK and POOL through the verdict and lists the
  outcomes. LOCK and POOL are recorded as detected or not detected, never asserted.

On a pull request that leaves the system under test unchanged, the gate is an A/A run. Its rate
of false FAILs has not been measured as such; it is expected to be the A/A rate above as long as
the profile and the runners are those of the campaign.
