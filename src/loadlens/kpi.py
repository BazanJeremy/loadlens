"""Key performance indicators of a run, overall and per transaction.

Definitions (docs/kpi.md) are chosen so every number can be recomputed by hand:
- latency percentiles and mean use successful samples only (failures are counted by the error
  rate; a fast connection refusal must not make latency look better);
- percentiles use the nearest-rank method: always an observed value, no interpolation;
- the duration is the run's whole window, from the earliest start to the latest end; the
  per-transaction throughput uses that same window, so transaction throughputs add up;
- Apdex counts failed samples as frustrated;
- CV is the population standard deviation of successful latencies divided by their mean.
`None` means "not computable from this run", never zero.
"""

import math
import statistics
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from loadlens.schema import Run, Samples, TransactionAggregate

PERCENTILES = (50, 90, 95, 99)
DEFAULT_APDEX_T_MS = 300


class Kpis(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int
    error_count: int
    error_rate: float | None
    p50_ms: float | None
    p90_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    mean_ms: float | None
    throughput_rps: float | None
    apdex: float | None
    cv: float | None


class RunKpis(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall: Kpis
    transactions: dict[str, Kpis]
    duration_s: float | None
    apdex_t_ms: int


def nearest_rank(sorted_values: Sequence[float], q: float) -> float:
    """Smallest observed value with at least q% of the values at or below it."""
    if not sorted_values:
        raise ValueError("no values")
    if not 0 < q <= 100:
        raise ValueError(f"percentile must be in (0, 100], got {q}")
    rank = math.ceil(q / 100 * len(sorted_values))
    return float(sorted_values[rank - 1])


def apdex(elapsed_ms: Sequence[int], success: Sequence[bool], t_ms: int) -> float | None:
    """(satisfied + tolerating / 2) / total. Satisfied: <= T; tolerating: <= 4T; failures and
    anything slower are frustrated."""
    if not elapsed_ms:
        return None
    satisfied = sum(1 for e, ok in zip(elapsed_ms, success, strict=True) if ok and e <= t_ms)
    tolerating = sum(
        1 for e, ok in zip(elapsed_ms, success, strict=True) if ok and t_ms < e <= 4 * t_ms
    )
    return (satisfied + tolerating / 2) / len(elapsed_ms)


def _kpis(
    elapsed_ms: Sequence[int], success: Sequence[bool], duration_s: float | None, t_ms: int
) -> Kpis:
    count = len(elapsed_ms)
    errors = sum(1 for ok in success if not ok)
    ok_latencies = sorted(e for e, ok in zip(elapsed_ms, success, strict=True) if ok)
    percentiles = {q: nearest_rank(ok_latencies, q) if ok_latencies else None for q in PERCENTILES}
    mean = statistics.fmean(ok_latencies) if ok_latencies else None
    cv = None
    if len(ok_latencies) >= 2 and mean:
        cv = statistics.pstdev(ok_latencies) / mean
    return Kpis(
        count=count,
        error_count=errors,
        error_rate=errors / count if count else None,
        p50_ms=percentiles[50],
        p90_ms=percentiles[90],
        p95_ms=percentiles[95],
        p99_ms=percentiles[99],
        mean_ms=mean,
        throughput_rps=count / duration_s if duration_s else None,
        apdex=apdex(elapsed_ms, success, t_ms),
        cv=cv,
    )


def _from_aggregate(agg: TransactionAggregate) -> Kpis:
    return Kpis(
        count=agg.count,
        error_count=agg.error_count,
        error_rate=agg.error_count / agg.count if agg.count else None,
        p50_ms=agg.p50_ms,
        p90_ms=agg.p90_ms,
        p95_ms=agg.p95_ms,
        p99_ms=agg.p99_ms,
        mean_ms=None,
        throughput_rps=None,
        apdex=None,
        cv=None,
    )


def drop_warmup(run: Run, warmup_s: float) -> Run:
    """Leave out the samples that started during the first `warmup_s` seconds, counted from the
    earliest sample. Metadata, including `started_at`, is unchanged."""
    if warmup_s < 0:
        raise ValueError(f"warm-up must be >= 0 seconds, got {warmup_s}")
    if warmup_s == 0:
        return run
    if run.samples is None:
        raise ValueError("a warm-up cannot be removed from a run that only has aggregates")
    samples = run.samples
    if not len(samples):
        return run
    cutoff = min(samples.start_ms) + warmup_s * 1000
    keep = [i for i, start in enumerate(samples.start_ms) if start >= cutoff]
    trimmed = Samples(
        start_ms=[samples.start_ms[i] for i in keep],
        elapsed_ms=[samples.elapsed_ms[i] for i in keep],
        transaction=[samples.transaction[i] for i in keep],
        success=[samples.success[i] for i in keep],
        response_code=[samples.response_code[i] for i in keep],
    )
    return run.model_copy(update={"samples": trimmed})


def compute(run: Run, apdex_t_ms: int = DEFAULT_APDEX_T_MS) -> RunKpis:
    if apdex_t_ms <= 0:
        raise ValueError(f"Apdex threshold must be > 0 ms, got {apdex_t_ms}")
    if run.aggregates is not None:
        return _compute_from_aggregates(run.aggregates, apdex_t_ms)

    samples = run.samples
    assert samples is not None  # guaranteed by Run's validator
    duration_s = None
    if len(samples):
        first_start = min(samples.start_ms)
        last_end = max(s + e for s, e in zip(samples.start_ms, samples.elapsed_ms, strict=True))
        duration_s = (last_end - first_start) / 1000

    by_transaction: dict[str, tuple[list[int], list[bool]]] = {}
    for name, elapsed, ok in zip(
        samples.transaction, samples.elapsed_ms, samples.success, strict=True
    ):
        latencies, flags = by_transaction.setdefault(name, ([], []))
        latencies.append(elapsed)
        flags.append(ok)

    return RunKpis(
        overall=_kpis(samples.elapsed_ms, samples.success, duration_s, apdex_t_ms),
        transactions={
            name: _kpis(latencies, flags, duration_s, apdex_t_ms)
            for name, (latencies, flags) in sorted(by_transaction.items())
        },
        duration_s=duration_s,
        apdex_t_ms=apdex_t_ms,
    )


def _compute_from_aggregates(aggregates: list[TransactionAggregate], apdex_t_ms: int) -> RunKpis:
    count = sum(a.count for a in aggregates)
    errors = sum(a.error_count for a in aggregates)
    # Percentiles of different transactions cannot be combined: the overall ones stay unknown.
    overall = Kpis(
        count=count,
        error_count=errors,
        error_rate=errors / count if count else None,
        p50_ms=None,
        p90_ms=None,
        p95_ms=None,
        p99_ms=None,
        mean_ms=None,
        throughput_rps=None,
        apdex=None,
        cv=None,
    )
    return RunKpis(
        overall=overall,
        transactions={a.transaction: _from_aggregate(a) for a in aggregates},
        duration_s=None,
        apdex_t_ms=apdex_t_ms,
    )
