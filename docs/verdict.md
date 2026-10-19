# Verdict

`loadlens verdict` tells whether a candidate is fit to ship, with its reasons: **PASS**,
**WARN**, **FAIL** or **INCONCLUSIVE**. It checks the candidate against SLOs and, when a baseline
measured on the same machine is given, looks for a regression with the detector of ADR-004.
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
These rules, and the options set aside, are recorded in
[ADR-005](adr/ADR-005-verdict-levels-and-ci-status.md).

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
2. relative change of the p95 of all successful samples of each arm: more than +10%;
3. Cliff's δ on the same window p95 values: at least 0.147.

All three: **FAIL** (regression). Two of three: **WARN** (weak regression), a rule declared on
2026-10-16, before the calibration campaign, and kept as declared. Its rate was measured
afterwards (below), not tuned.

The first five values of `regression:` in `config/slo.yaml` are the calibrated ones; a test
checks that they match the detector the campaign measured. Changed, they leave the measured
false-positive rate without a source.

## INCONCLUSIVE

A comparison was asked for and could not be made:

- no baseline run, or a run without raw samples (aggregates cannot be compared);
- a transaction without any successful sample in one of the arms;
- fewer than 10 windows in an arm, for a transaction (`min_windows_per_arm`, declared on
  2026-10-18, not calibrated; every comparison of the calibration campaign had 24).

Nothing was measured: a candidate segment without any sample, baseline or not, or an A-B-B-A run
that cannot be used, for instance a segment that overran its schedule by more than 30 s
([ADR-003](adr/ADR-003-abba-protocol-on-one-machine.md)). This INCONCLUSIVE also **fails the CI
job** (check `no_measurement`): the check did not take place at all.

Run stability is not a reason: no instrument has passed a calibration yet (ADR-004). Without a
baseline, the verdict rests on SLOs alone and a note says that regressions were not checked.

## Measured behaviour

**Regression rules on the calibration campaign** (run 39058130424, 2026-10-17, 4-CPU
`ubuntu-24.04` runners, 60 s hold). The campaign report holds the per-transaction comparisons,
not the KPIs, so this applies the regression rules only, without the SLOs:

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

**Full verdict on the CI runners** (`Evidence` workflow run 39241955097, 2026-10-19, 3 A-B-B-A
runs per mode, 60 s hold, `ubuntu-24.04` runners), SLOs included:

| Runs | PASS | WARN | FAIL |
|---|---|---|---|
| A/A (3) | 2 | 0 | 1 |
| N+1 (3) | 0 | 0 | 3 |
| LOCK (3) | 1 | 0 | 2 |
| POOL (3) | 2 | 0 | 1 |

- No SLO was broken in any of the 12 runs.
- The A/A FAIL (`none-3`) and the POOL FAIL (`POOL-2`) are one-millisecond steps again:
  `get_payment` p95 5 → 6 ms (+20%), `get_statement` p95 7 → 8 ms (+14%). This is the weakness
  ADR-004 describes, under a p95 of 10 ms.
- Three runs per mode measure no rate. They are not pooled with the campaign, whose criteria
  were declared before it ran.

**Full verdict on the local pilot** (2026-10-17, one A-B-B-A run each, on a local machine with 12
CPUs according to `meta.json`, same profile; runs not committed): the 3 A/A runs PASS; N+1 and
LOCK FAIL through a regression; POOL FAIL through the error rate, 16.5% in segment B2 and 0 in
B1. The 196 errors of B2 are all `java.net.SocketException` (a transport error, no HTTP
response), all started within 0.34 s, each lasting at most 830 ms. The pilot did not record the
host wall clock yet, so a suspended host cannot be ruled out. Cause unknown.

**POOL errors on the CI runners:** none in the campaign. The arrival schedules are fixed, so each
segment receives the same arrivals; in the 5 POOL runs, the candidate segments hold exactly as
many successful samples as the baseline ones, while A/A runs differ by at most one.

**Throughput on the CI single run** (10 s ramp, 120 s hold, CI runs 39121427078 and 39210874408):
the same counts in both runs, 477, 1,193 and 716 samples, that is 3.99, 9.99 and 5.99 per second
against floors of 3.8, 9.5 and 5.7. The arrival schedules use fixed seeds, so these counts repeat
from run to run. In an open workload model the arrivals do not wait for the system under test:
this SLO checks mainly that the planned load was sent, the role k6 gives to its
`dropped_iterations` metric.

## In CI

- **Pull requests, `gate` job:** the system under test of the base commit (A) against the pull
  request's (B), A-B-B-A on one runner. Both arms use the pull request's `compose.yaml` and
  JMeter plan; a step checks that each segment ran its arm's image. FAIL fails the job. So far
  this check has only seen identical images: in run 39121427078 the pull request did not change
  the system under test, and the four segments ran the same image.
- **Pull requests, `proof` job:** an A-B-B-A run with N+1 switched on in B. The job passes only
  if the verdict is FAIL with a regression on `get_statement`.
- **Every push and pull request, `jmeter` job:** the single run, SLOs only.
- WARN and INCONCLUSIVE leave the job green, with a warning annotation; FAIL turns it red, and
  so does an INCONCLUSIVE where nothing was measured (`loadlens verdict --ci-status`).
- **Manual `Evidence` workflow:** runs A/A, N+1, LOCK and POOL through the verdict and lists the
  outcomes. LOCK and POOL are recorded as detected or not detected, never asserted.

On a pull request that leaves the system under test unchanged, the gate is an A/A run. Its rate
of false FAILs has not been measured as such; it is expected to be the A/A rate above as long as
the profile and the runners are those of the campaign.
