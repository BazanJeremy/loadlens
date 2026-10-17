"""Runtime configuration, read from environment variables.

Standard library only, so it can be unit-tested without the API dependencies.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

_TRUE = {"1", "true"}
_FALSE = {"", "0", "false"}

# Connection pool used in nominal mode, and the undersized one SUT_REGRESSION_POOL switches to.
NOMINAL_POOL_SIZE = 10
NOMINAL_MAX_OVERFLOW = 10
REGRESSION_POOL_SIZE = 1
REGRESSION_MAX_OVERFLOW = 0


def parse_flag(name: str, environ: Mapping[str, str]) -> bool:
    """Read a boolean flag. Unset means off; an unrecognized value is an error, never a guess."""
    raw = environ.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"{name} must be one of 0, 1, true, false (got {raw!r})")


@dataclass(frozen=True)
class Settings:
    database_url: str
    regression_n_plus_one: bool
    regression_lock: bool
    regression_pool: bool

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Settings":
        database_url = environ.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        return cls(
            database_url=database_url,
            regression_n_plus_one=parse_flag("SUT_REGRESSION_N_PLUS_ONE", environ),
            regression_lock=parse_flag("SUT_REGRESSION_LOCK", environ),
            regression_pool=parse_flag("SUT_REGRESSION_POOL", environ),
        )

    @property
    def pool_size(self) -> int:
        return REGRESSION_POOL_SIZE if self.regression_pool else NOMINAL_POOL_SIZE

    @property
    def max_overflow(self) -> int:
        return REGRESSION_MAX_OVERFLOW if self.regression_pool else NOMINAL_MAX_OVERFLOW

    def regressions(self) -> dict[str, bool]:
        return {
            "n_plus_one": self.regression_n_plus_one,
            "lock": self.regression_lock,
            "pool": self.regression_pool,
        }
