from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from loadlens.schema import Run, RunMetadata, Samples, Tool, TransactionAggregate

META = RunMetadata(
    tool=Tool.JMETER, source_file="x.jtl", started_at=datetime(2026, 1, 1, tzinfo=UTC)
)


def samples(**overrides):
    columns = {
        "start_ms": [0, 10],
        "elapsed_ms": [5, 6],
        "transaction": ["a", "b"],
        "success": [True, False],
        "response_code": ["200", "500"],
    }
    return Samples(**(columns | overrides))


def test_samples_columns_must_have_the_same_length():
    with pytest.raises(ValidationError, match="different lengths"):
        samples(elapsed_ms=[5])


def test_negative_elapsed_is_rejected():
    with pytest.raises(ValidationError, match="elapsed_ms must be >= 0"):
        samples(elapsed_ms=[5, -1])


def test_a_run_needs_samples_or_aggregates():
    with pytest.raises(ValidationError, match="exactly one"):
        Run(metadata=META)


def test_a_run_cannot_carry_both_samples_and_aggregates():
    aggregate = TransactionAggregate(transaction="a", count=1, error_count=0)
    with pytest.raises(ValidationError, match="exactly one"):
        Run(metadata=META, samples=samples(), aggregates=[aggregate])


def test_aggregate_errors_cannot_exceed_count():
    with pytest.raises(ValidationError, match="error_count cannot exceed count"):
        TransactionAggregate(transaction="a", count=1, error_count=2)


def test_start_time_must_carry_a_timezone():
    with pytest.raises(ValidationError):
        RunMetadata(tool=Tool.JMETER, source_file="x.jtl", started_at=datetime(2026, 1, 1))


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        RunMetadata(tool=Tool.JMETER, source_file="x.jtl", started_at=None, guessed="value")


def test_samples_length():
    assert len(samples()) == 2
