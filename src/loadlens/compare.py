"""Baseline versus candidate comparison, per transaction.

Three candidate methods are computed side by side; which one decides a regression is settled by
the calibration step (docs/calibration.md), not assumed here:

- raw: one-sided Mann-Whitney U test and Cliff's delta on every successful sample;
- windowed: the same tests on per-window p95 values, which weakens the autocorrelation between
  consecutive samples at the cost of far fewer data points;
- bootstrap: moving-block bootstrap interval of the relative p95 change.

Each arm (baseline, candidate) may hold several segments, e.g. A1 + A2 in an A-B-B-A run.
Only successful samples enter latency comparisons, as in loadlens.kpi.
"""

import math
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy.stats import mannwhitneyu

from loadlens.kpi import nearest_rank
from loadlens.schema import Run

DEFAULT_WINDOW_S = 5.0
DEFAULT_MIN_WINDOW_SAMPLES = 5
DEFAULT_BOOTSTRAP_REPLICATES = 2000
DEFAULT_BLOCK_S = 1.0


class TransactionComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    transaction: str
    baseline_count: int
    candidate_count: int
    p95_baseline_ms: float | None
    p95_candidate_ms: float | None
    delta_p95_rel: float | None
    raw_p_value: float | None
    raw_cliffs_delta: float | None
    windows_baseline: int
    windows_candidate: int
    windowed_p_value: float | None
    windowed_cliffs_delta: float | None
    bootstrap_delta_p95_low: float | None  # 5th percentile of the relative p95 change
    bootstrap_delta_p95_high: float | None  # 95th percentile


def cliffs_delta(candidate: Sequence[float], baseline: Sequence[float]) -> float:
    """P(candidate > baseline) - P(candidate < baseline), exact, in O(n log n)."""
    if not candidate or not baseline:
        raise ValueError("both groups need at least one value")
    base = np.sort(np.asarray(baseline, dtype=float))
    cand = np.asarray(candidate, dtype=float)
    below = np.searchsorted(base, cand, side="left")  # baseline values < each candidate value
    above = len(base) - np.searchsorted(base, cand, side="right")  # baseline values > it
    return float((below.sum() - above.sum()) / (len(cand) * len(base)))


def mann_whitney_greater(candidate: Sequence[float], baseline: Sequence[float]) -> float:
    """One-sided p-value of H1: candidate latencies are stochastically greater."""
    if not candidate or not baseline:
        raise ValueError("both groups need at least one value")
    return float(
        mannwhitneyu(candidate, baseline, alternative="greater", method="asymptotic").pvalue
    )


def _successful(runs: Sequence[Run], transaction: str) -> list[list[tuple[int, int]]]:
    """Per segment: (start_ms, elapsed_ms) of the transaction's successful samples, time-ordered."""
    segments = []
    for run in runs:
        s = run.samples
        if s is None:
            raise ValueError("comparison needs raw samples; this run only has aggregates")
        rows = [
            (start, elapsed)
            for start, elapsed, name, ok in zip(
                s.start_ms, s.elapsed_ms, s.transaction, s.success, strict=True
            )
            if ok and name == transaction
        ]
        segments.append(sorted(rows))
    return segments


def window_p95(
    segment: Sequence[tuple[int, int]], window_s: float, min_samples: int
) -> list[float]:
    """Nearest-rank p95 of each window of `window_s` seconds, windows counted from the segment's
    first sample. Windows with fewer than `min_samples` samples are left out."""
    if not segment:
        return []
    t0 = segment[0][0]
    windows: dict[int, list[int]] = {}
    for start, elapsed in segment:
        windows.setdefault(int((start - t0) // (window_s * 1000)), []).append(elapsed)
    return [
        nearest_rank(sorted(values), 95)
        for _, values in sorted(windows.items())
        if len(values) >= min_samples
    ]


def _block_bootstrap_p95(
    segments: Sequence[Sequence[tuple[int, int]]],
    replicates: int,
    block_s: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """p95 of `replicates` moving-block resamples of an arm.

    One block length for the whole arm: the number of samples the arm records in `block_s`
    seconds on average. Blocks never cross a segment boundary; a segment shorter than one block
    contributes no block. Each resample has as many values as the arm.
    """
    values = np.array([e for seg in segments for _, e in seg], dtype=float)
    total = len(values)
    duration_s = sum((seg[-1][0] - seg[0][0]) / 1000 for seg in segments if seg)
    span = min(total, max(1, math.ceil(block_s * total / max(duration_s, 1e-9))))
    block_starts = []
    offset = 0
    for seg in segments:
        block_starts.extend(range(offset, offset + len(seg) - span + 1))
        offset += len(seg)
    if not block_starts:  # every segment shorter than one block: fall back to one block per arm
        block_starts, span = [0], total
    starts = np.asarray(block_starts)
    draws = math.ceil(total / span)
    picked = starts[rng.integers(0, len(starts), size=(replicates, draws))]
    resamples = values[picked[..., None] + np.arange(span)].reshape(replicates, -1)[:, :total]
    return np.quantile(resamples, 0.95, axis=1, method="inverted_cdf")


def compare_transaction(
    baseline: Sequence[Run],
    candidate: Sequence[Run],
    transaction: str,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    min_window_samples: int = DEFAULT_MIN_WINDOW_SAMPLES,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    block_s: float = DEFAULT_BLOCK_S,
    seed: int = 0,
) -> TransactionComparison:
    base_segments = _successful(baseline, transaction)
    cand_segments = _successful(candidate, transaction)
    base = [e for seg in base_segments for _, e in seg]
    cand = [e for seg in cand_segments for _, e in seg]

    p95_b = nearest_rank(sorted(base), 95) if base else None
    p95_c = nearest_rank(sorted(cand), 95) if cand else None
    delta = (p95_c - p95_b) / p95_b if p95_b and p95_c is not None else None

    win_b = [v for seg in base_segments for v in window_p95(seg, window_s, min_window_samples)]
    win_c = [v for seg in cand_segments for v in window_p95(seg, window_s, min_window_samples)]

    low = high = None
    if base and cand and p95_b:
        rng = np.random.default_rng(seed)
        boot_b = _block_bootstrap_p95(base_segments, replicates, block_s, rng)
        boot_c = _block_bootstrap_p95(cand_segments, replicates, block_s, rng)
        valid = boot_b > 0  # a 0 ms baseline p95 has no relative change
        if valid.any():
            rel = (boot_c[valid] - boot_b[valid]) / boot_b[valid]
            low, high = (float(q) for q in np.quantile(rel, [0.05, 0.95]))

    return TransactionComparison(
        transaction=transaction,
        baseline_count=len(base),
        candidate_count=len(cand),
        p95_baseline_ms=p95_b,
        p95_candidate_ms=p95_c,
        delta_p95_rel=delta,
        raw_p_value=mann_whitney_greater(cand, base) if base and cand else None,
        raw_cliffs_delta=cliffs_delta(cand, base) if base and cand else None,
        windows_baseline=len(win_b),
        windows_candidate=len(win_c),
        windowed_p_value=mann_whitney_greater(win_c, win_b) if win_b and win_c else None,
        windowed_cliffs_delta=cliffs_delta(win_c, win_b) if win_b and win_c else None,
        bootstrap_delta_p95_low=low,
        bootstrap_delta_p95_high=high,
    )


def compare_runs(
    baseline: Sequence[Run], candidate: Sequence[Run], **options: float
) -> list[TransactionComparison]:
    """One comparison per transaction present in either arm, sorted by name."""
    names: set[str] = set()
    for run in [*baseline, *candidate]:
        if run.samples is None:
            raise ValueError("comparison needs raw samples; this run only has aggregates")
        names.update(run.samples.transaction)
    return [compare_transaction(baseline, candidate, name, **options) for name in sorted(names)]
