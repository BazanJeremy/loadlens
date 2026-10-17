# KPI definitions

Implemented in `src/loadlens/kpi.py`. Every definition is chosen so that a number can be
recomputed by hand from the samples; `tests/test_kpi.py` does exactly that on ten real JMeter
rows. `None` always means "not computable from this run", never zero.

| KPI | Definition |
|---|---|
| `count`, `error_count` | Number of samples, and of samples whose `success` flag is false |
| `error_rate` | `error_count / count`; `None` for a run without samples |
| `p50_ms` … `p99_ms` | Nearest-rank percentile of the **successful** samples' latency: the value at rank `ceil(q/100 × n)` of the sorted latencies. Always an observed value, no interpolation |
| `mean_ms` | Arithmetic mean of the successful samples' latency |
| `duration_s` | Run window: latest sample end (`start + elapsed`) minus earliest sample start |
| `throughput_rps` | `count / duration_s`, overall and per transaction. Per-transaction throughput uses the run window, so transaction throughputs add up to the overall one |
| `apdex` | `(satisfied + tolerating / 2) / count` with threshold T (default 300 ms): satisfied = successful and ≤ T, tolerating = successful and ≤ 4T, every other sample (slower, or failed) is frustrated |
| `cv` | Population standard deviation of the successful samples' latency divided by their mean; needs at least two successful samples |

## Choices and their reasons

- **Latency uses successful samples only.** Failures are measured by the error rate. Counting
  them in latency would let a fast failure (a refused connection takes a few milliseconds) make
  latency look better.
- **Nearest rank** rather than interpolation: the result is always a latency that was actually
  observed, and it can be checked by counting.
- **Failures are frustrated in Apdex.** This is loadlens' choice, also made by tools such as
  SmartBear AlertSite and Honeycomb. Whether the official Apdex specification mandates it is
  unknown: the specification text was not reachable when this was written (2026-10-17).
- **Percentiles are never merged.** For a source that only exports per-transaction aggregates,
  overall percentiles stay `None`: they cannot be derived from per-transaction percentiles.
- **Latency is JMeter's `elapsed`** (time to last byte), not `Latency` (time to first byte).

## Warm-up

`drop_warmup` (CLI: `--warmup-s`) leaves out the samples that started during the first N seconds,
counted from the earliest sample. The CI passes the plan's ramp duration, so KPIs describe the
hold phase only.

## Resolution

JTL latencies are whole milliseconds (JMeter manual, 12.4). Measured locally on 2026-10-17, the
nominal p95 of the CI profile is 9 ms (`load/jmeter/README.en.md`): a 10% change of it (0.9 ms)
is below that resolution.

## What `cv` is not (yet)

`cv` describes the spread of one run's latencies. Whether it is the right stability criterion
for the INCONCLUSIVE verdict is decided by measurement in the statistical calibration step, not
here. First measurements of a nominal run of the CI profile (2026-10-17): raw-latency CV of 0.47
overall and 0.32 to 0.38 per transaction locally, 0.46 overall and 0.35 to 0.42 per transaction
in CI (`load/jmeter/README.en.md`) — far above a 15% threshold on a healthy run.
