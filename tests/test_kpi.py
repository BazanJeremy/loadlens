from datetime import UTC, datetime

import pytest

from loadlens.adapters.jmeter import read_jtl
from loadlens.kpi import apdex, compute, nearest_rank
from loadlens.schema import Run, RunMetadata, Samples, Tool, TransactionAggregate

META = RunMetadata(tool=Tool.JMETER, source_file="x", started_at=datetime(2026, 1, 1, tzinfo=UTC))


def run_of(elapsed, success=None, transaction=None, start=None):
    n = len(elapsed)
    return Run(
        metadata=META,
        samples=Samples(
            start_ms=start or [0] * n,
            elapsed_ms=elapsed,
            transaction=transaction or ["t"] * n,
            success=success or [True] * n,
            response_code=["200"] * n,
        ),
    )


# --- hand-computed on 10 real JMeter rows ---------------------------------------------------
# fixtures/jmeter/2026-10-17-nominal-short-head10.jtl, all successful:
#   start (ms, -1792224000000)  elapsed  label
#   111088  33  get_statement      111711   4  get_payment
#   111565   6  get_payment        111831   9  create_payment
#   111571   8  get_statement      111962   4  get_payment
#   111668   6  get_statement      112065   8  create_payment
#   111701   5  get_payment        112132   5  get_payment
# Sorted latencies: 4 4 5 5 6 6 8 8 9 33; sum 88.
# Duration: latest end 112132 + 5 = 112137, minus earliest start 111088 = 1049 ms.


@pytest.fixture
def head10(jmeter_fixture):
    return compute(read_jtl(jmeter_fixture("2026-10-17-nominal-short-head10.jtl")))


def test_hand_computed_overall_kpis(head10):
    k = head10.overall
    assert (k.count, k.error_count, k.error_rate) == (10, 0, 0.0)
    # Nearest rank on n = 10: p50 -> rank 5, p90 -> rank 9, p95 and p99 -> rank 10.
    assert (k.p50_ms, k.p90_ms, k.p95_ms, k.p99_ms) == (6.0, 9.0, 33.0, 33.0)
    assert k.mean_ms == pytest.approx(8.8)  # 88 / 10
    assert head10.duration_s == pytest.approx(1.049)
    assert k.throughput_rps == pytest.approx(10 / 1.049)
    assert k.apdex == 1.0  # every sample <= 300 ms
    # Squared deviations from 8.8 sum to 677.6; population variance 67.76.
    assert k.cv == pytest.approx(67.76**0.5 / 8.8)


def test_hand_computed_per_transaction_kpis(head10):
    statement = head10.transactions["get_statement"]  # 33 8 6 -> sorted 6 8 33
    assert (statement.count, statement.p50_ms, statement.p90_ms) == (3, 8.0, 33.0)
    assert statement.mean_ms == pytest.approx(47 / 3)

    payment = head10.transactions["get_payment"]  # 6 5 4 4 5 -> sorted 4 4 5 5 6
    assert (payment.count, payment.p50_ms, payment.p90_ms, payment.p99_ms) == (5, 5.0, 6.0, 6.0)
    assert payment.mean_ms == pytest.approx(4.8)
    assert payment.cv == pytest.approx(0.56**0.5 / 4.8)  # squared deviations sum 2.8 over 5

    create = head10.transactions["create_payment"]  # 9 8 -> sorted 8 9
    assert (create.count, create.p50_ms, create.p95_ms) == (2, 8.0, 9.0)


def test_transaction_throughputs_add_up_to_the_overall_one(head10):
    total = sum(k.throughput_rps for k in head10.transactions.values())
    assert total == pytest.approx(head10.overall.throughput_rps)
    assert head10.transactions["get_payment"].throughput_rps == pytest.approx(5 / 1.049)


# --- edge cases from real runs --------------------------------------------------------------


def test_empty_run_has_nothing_computable(jmeter_fixture):
    kpis = compute(read_jtl(jmeter_fixture("2026-10-17-empty.jtl")))
    k = kpis.overall
    assert (k.count, k.error_count) == (0, 0)
    assert k.error_rate is k.p50_ms is k.p99_ms is k.mean_ms is None
    assert k.throughput_rps is k.apdex is k.cv is None
    assert kpis.duration_s is None
    assert kpis.transactions == {}


def test_all_errors_run(jmeter_fixture):
    k = compute(read_jtl(jmeter_fixture("2026-10-17-all-errors.jtl"))).overall
    assert (k.count, k.error_count, k.error_rate) == (70, 70, 1.0)
    # No successful sample: latency figures are unknown, not zero.
    assert k.p50_ms is k.p95_ms is k.mean_ms is k.cv is None
    assert k.apdex == 0.0  # failures are frustrated
    assert k.throughput_rps > 0


def test_single_transaction_overall_equals_the_transaction(jmeter_fixture):
    kpis = compute(read_jtl(jmeter_fixture("2026-10-17-single-transaction.jtl")))
    assert list(kpis.transactions) == ["get_payment"]
    assert kpis.transactions["get_payment"] == kpis.overall


# --- definitions -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "expected"), [(50, 50.0), (90, 90.0), (95, 95.0), (99, 99.0), (100, 100.0)]
)
def test_nearest_rank_on_1_to_100(q, expected):
    assert nearest_rank(list(range(1, 101)), q) == expected


def test_nearest_rank_returns_an_observed_value():
    assert nearest_rank([10, 20], 50) == 10.0  # rank ceil(1.0) = 1, no interpolation
    assert nearest_rank([10, 20], 51) == 20.0
    assert nearest_rank([7], 99) == 7.0


@pytest.mark.parametrize("q", [0, -1, 101])
def test_nearest_rank_rejects_out_of_range_percentiles(q):
    with pytest.raises(ValueError, match="percentile"):
        nearest_rank([1, 2], q)


def test_apdex_zone_boundaries():
    # T = 300: 300 satisfied, 301 and 1200 tolerating, 1201 frustrated, a failure frustrated.
    elapsed = [300, 301, 1200, 1201, 10]
    success = [True, True, True, True, False]
    assert apdex(elapsed, success, 300) == pytest.approx((1 + 2 / 2) / 5)


def test_latency_figures_ignore_failed_samples():
    k = compute(run_of([100, 1, 1], success=[True, False, False])).overall
    assert (k.p50_ms, k.mean_ms, k.error_rate) == (100.0, 100.0, pytest.approx(2 / 3))


def test_cv_needs_two_successful_samples():
    assert compute(run_of([100])).overall.cv is None
    assert compute(run_of([100, 100])).overall.cv == 0.0


def test_zero_length_window_gives_no_throughput():
    k = compute(run_of([0], start=[5])).overall
    assert k.throughput_rps is None


def test_custom_apdex_threshold_is_recorded():
    kpis = compute(run_of([400]), apdex_t_ms=500)
    assert (kpis.apdex_t_ms, kpis.overall.apdex) == (500, 1.0)


# --- aggregate-only runs ---------------------------------------------------------------------


def test_aggregate_only_run_keeps_source_figures_and_never_merges_percentiles():
    run = Run(
        metadata=META,
        aggregates=[
            TransactionAggregate(transaction="a", count=90, error_count=9, p95_ms=120.0),
            TransactionAggregate(transaction="b", count=10, error_count=1, p95_ms=40.0),
        ],
    )
    kpis = compute(run)
    assert kpis.transactions["a"].p95_ms == 120.0
    assert kpis.transactions["a"].error_rate == pytest.approx(0.1)
    assert (kpis.overall.count, kpis.overall.error_count) == (100, 10)
    assert kpis.overall.p95_ms is None  # cannot be derived from per-transaction percentiles
    assert kpis.overall.apdex is kpis.overall.throughput_rps is None
