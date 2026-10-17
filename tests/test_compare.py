import random
from datetime import UTC, datetime

import numpy as np
import pytest
from scipy.stats import mannwhitneyu

from loadlens.compare import (
    cliffs_delta,
    compare_runs,
    compare_transaction,
    mann_whitney_greater,
    window_p95,
)
from loadlens.kpi import nearest_rank
from loadlens.schema import Run, RunMetadata, Samples, Tool, TransactionAggregate

META = RunMetadata(tool=Tool.JMETER, source_file="x", started_at=datetime(2026, 1, 1, tzinfo=UTC))


def run_of(elapsed, transaction="t", step_ms=100, success=None):
    n = len(elapsed)
    return Run(
        metadata=META,
        samples=Samples(
            start_ms=[i * step_ms for i in range(n)],
            elapsed_ms=list(elapsed),
            transaction=[transaction] * n if isinstance(transaction, str) else transaction,
            success=success or [True] * n,
            response_code=["200"] * n,
        ),
    )


def brute_force_delta(candidate, baseline):
    gt = sum(1 for c in candidate for b in baseline if c > b)
    lt = sum(1 for c in candidate for b in baseline if c < b)
    return (gt - lt) / (len(candidate) * len(baseline))


# --- Cliff's delta ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "baseline", "expected"),
    [
        ([3], [1, 2], 1.0),
        ([1], [2, 3], -1.0),
        ([2], [1, 2, 3], 0.0),  # one greater, one tie, one smaller
        ([1, 2], [1, 3], -0.25),  # pairs: tie, <, >, <  ->  (1 - 2) / 4
    ],
)
def test_cliffs_delta_hand_computed(candidate, baseline, expected):
    assert cliffs_delta(candidate, baseline) == pytest.approx(expected)


def test_cliffs_delta_matches_brute_force_with_many_ties():
    rng = random.Random(3)
    for _ in range(20):
        cand = [rng.randint(1, 8) for _ in range(rng.randint(1, 40))]
        base = [rng.randint(1, 8) for _ in range(rng.randint(1, 40))]
        assert cliffs_delta(cand, base) == pytest.approx(brute_force_delta(cand, base))


def test_cliffs_delta_equals_2u_over_n1n2_minus_1():
    rng = random.Random(5)
    cand = [rng.randint(1, 20) for _ in range(60)]
    base = [rng.randint(1, 20) for _ in range(45)]
    u = mannwhitneyu(cand, base, alternative="greater").statistic
    assert cliffs_delta(cand, base) == pytest.approx(2 * u / (60 * 45) - 1)


def test_cliffs_delta_needs_values():
    with pytest.raises(ValueError):
        cliffs_delta([], [1])


# --- Mann-Whitney ----------------------------------------------------------------------------


def test_mann_whitney_detects_a_clear_increase():
    assert mann_whitney_greater(list(range(100, 200)), list(range(0, 100))) < 1e-6


def test_mann_whitney_is_one_sided():
    assert mann_whitney_greater(list(range(0, 100)), list(range(100, 200))) > 0.999


def test_mann_whitney_on_identical_groups_is_not_significant():
    values = list(range(50))
    assert mann_whitney_greater(values, values) > 0.4


# --- percentile definition used by the bootstrap --------------------------------------------


def test_numpy_inverted_cdf_is_the_nearest_rank_definition():
    rng = random.Random(11)
    for n in (1, 2, 7, 50, 999):
        values = sorted(rng.randint(1, 300) for _ in range(n))
        assert np.quantile(values, 0.95, method="inverted_cdf") == nearest_rank(values, 95)


# --- windows ---------------------------------------------------------------------------------


def test_window_p95_hand_computed():
    # 100 samples, one every 100 ms, elapsed = index. 5 s windows hold indices 0-49 and 50-99.
    # Nearest rank on 50 values: rank ceil(0.95 * 50) = 48 -> values 47 and 97.
    segment = [(i * 100, i) for i in range(100)]
    assert window_p95(segment, 5.0, 5) == [47.0, 97.0]


def test_sparse_windows_are_left_out():
    segment = [(0, 1), (100, 2), (6000, 3)]  # 2 samples in window 0, 1 in window 1
    assert window_p95(segment, 5.0, 2) == [2.0]
    assert window_p95([], 5.0, 1) == []


# --- full comparison -------------------------------------------------------------------------


def test_identical_arms_show_no_change():
    rng = random.Random(1)
    elapsed = [rng.randint(3, 15) for _ in range(600)]
    result = compare_transaction([run_of(elapsed)], [run_of(elapsed)], "t", replicates=200)
    assert result.delta_p95_rel == 0.0
    assert result.raw_cliffs_delta == 0.0
    assert result.raw_p_value > 0.4
    assert result.bootstrap_delta_p95_low <= 0.0 <= result.bootstrap_delta_p95_high


def test_doubled_latency_is_detected_by_every_method():
    rng = random.Random(2)
    base = [rng.randint(3, 15) for _ in range(600)]
    cand = [2 * e for e in base]
    result = compare_transaction([run_of(base)], [run_of(cand)], "t", replicates=200)
    assert result.delta_p95_rel == pytest.approx(1.0)
    assert result.raw_p_value < 1e-6
    assert result.raw_cliffs_delta > 0.5
    assert result.windowed_p_value < 0.01
    assert result.bootstrap_delta_p95_low > 0.5


def test_segments_are_pooled_per_arm():
    a1, a2 = run_of([5] * 100), run_of([7] * 100)
    result = compare_transaction([a1, a2], [a1, a2], "t", replicates=50)
    assert (result.baseline_count, result.candidate_count) == (200, 200)
    assert result.windows_baseline == result.windows_candidate == 4  # 10 s per segment, 5 s windows


def test_bootstrap_is_reproducible_with_a_seed():
    rng = random.Random(4)
    base = [rng.randint(3, 15) for _ in range(300)]
    cand = [rng.randint(3, 16) for _ in range(300)]
    first = compare_transaction([run_of(base)], [run_of(cand)], "t", replicates=100, seed=9)
    again = compare_transaction([run_of(base)], [run_of(cand)], "t", replicates=100, seed=9)
    assert first == again


def test_failed_samples_are_left_out():
    run = run_of([5, 500, 5], success=[True, False, True])
    result = compare_transaction([run], [run], "t", replicates=20)
    assert result.baseline_count == 2
    assert result.p95_baseline_ms == 5.0


def test_a_transaction_missing_from_one_arm_has_no_statistics():
    base = run_of([5] * 20, transaction="a")
    cand = run_of([5] * 20, transaction="b")
    results = {r.transaction: r for r in compare_runs([base], [cand], replicates=20)}
    assert list(results) == ["a", "b"]
    assert results["a"].candidate_count == 0
    assert results["a"].raw_p_value is results["a"].delta_p95_rel is None
    assert results["a"].bootstrap_delta_p95_low is None


def test_aggregate_only_runs_cannot_be_compared():
    run = Run(
        metadata=META, aggregates=[TransactionAggregate(transaction="a", count=1, error_count=0)]
    )
    with pytest.raises(ValueError, match="raw samples"):
        compare_runs([run], [run])
