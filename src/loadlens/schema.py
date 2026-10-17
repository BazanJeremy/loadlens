"""Common result model: every adapter produces a `Run`, every analysis consumes one.

A run carries either raw samples (enough for statistics) or per-transaction aggregates
(for sources that only export summaries). Never both: one source of truth per run.
Unknown values are `None`, never a guess.
"""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Tool(StrEnum):
    JMETER = "jmeter"
    LOADRUNNER_DEVWEB = "loadrunner-devweb"


class Machine(BaseModel):
    """Where the load was generated. Every field is optional: None means unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    os: str | None = None
    cpu_model: str | None = None
    cpu_count: int | None = Field(default=None, gt=0)


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: Tool
    # None when the result file does not carry it (a JTL does not record the JMeter version).
    tool_version: str | None = None
    source_file: str
    # Start of the earliest sample; None for a run without samples.
    started_at: AwareDatetime | None
    # Load profile as declared by whoever launched the run (rates, durations...).
    profile: dict[str, str] = Field(default_factory=dict)
    machine: Machine | None = None


class Samples(BaseModel):
    """Column-oriented samples: index i in every list describes sample i."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_ms: list[int]  # epoch milliseconds, start of the sample
    elapsed_ms: list[int]  # time to last byte
    transaction: list[str]
    success: list[bool]
    response_code: list[str]  # kept as text: tools write non-numeric codes for transport errors

    @model_validator(mode="after")
    def _columns_are_consistent(self) -> Self:
        lengths = {
            len(self.start_ms),
            len(self.elapsed_ms),
            len(self.transaction),
            len(self.success),
            len(self.response_code),
        }
        if len(lengths) != 1:
            raise ValueError(f"sample columns have different lengths: {sorted(lengths)}")
        if any(e < 0 for e in self.elapsed_ms):
            raise ValueError("elapsed_ms must be >= 0")
        return self

    def __len__(self) -> int:
        return len(self.start_ms)


class TransactionAggregate(BaseModel):
    """Figures a source computed itself. Percentiles are optional: not every source has them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction: str
    count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    p50_ms: float | None = None
    p90_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None

    @model_validator(mode="after")
    def _errors_within_count(self) -> Self:
        if self.error_count > self.count:
            raise ValueError("error_count cannot exceed count")
        return self


class Run(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: RunMetadata
    samples: Samples | None = None
    aggregates: list[TransactionAggregate] | None = None

    @model_validator(mode="after")
    def _exactly_one_source_of_truth(self) -> Self:
        if (self.samples is None) == (self.aggregates is None):
            raise ValueError("a run carries either samples or aggregates, exactly one of them")
        return self
