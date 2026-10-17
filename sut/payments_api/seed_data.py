"""Deterministic seed data. Standard library only, so the generators can be unit-tested
without a database: the same configuration always yields the same rows."""

import os
import random
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

CATEGORIES = (
    "groceries",
    "transport",
    "utilities",
    "restaurants",
    "travel",
    "electronics",
    "health",
    "entertainment",
)
INITIAL_BALANCE_CENTS = 1_000_000_000
CURRENCY = "EUR"
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
PAYMENT_INTERVAL = timedelta(minutes=1)
MIN_SEED_AMOUNT_CENTS = 100
MAX_SEED_AMOUNT_CENTS = 50_000


@dataclass(frozen=True)
class SeedConfig:
    accounts: int = 1_000
    merchants: int = 5_000
    payments: int = 100_000
    random_seed: int = 42

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "SeedConfig":
        defaults = cls()
        config = cls(
            accounts=int(environ.get("SEED_ACCOUNTS", defaults.accounts)),
            merchants=int(environ.get("SEED_MERCHANTS", defaults.merchants)),
            payments=int(environ.get("SEED_PAYMENTS", defaults.payments)),
            random_seed=int(environ.get("SEED_RANDOM_SEED", defaults.random_seed)),
        )
        if config.accounts < 2 or config.merchants < 1 or config.payments < 0:
            raise ValueError(f"invalid seed configuration: {config}")
        return config

    @property
    def empty_account_id(self) -> int:
        """The last account is seeded with a zero balance and no payment, so the
        insufficient-funds path can be exercised. Load plans must not target it."""
        return self.accounts

    def _rng(self, table: str) -> random.Random:
        # One generator per table: changing one table's size does not reshuffle the others.
        return random.Random(f"{self.random_seed}/{table}")


def merchants(config: SeedConfig) -> Iterator[tuple[int, str, str]]:
    rng = config._rng("merchants")
    for merchant_id in range(1, config.merchants + 1):
        yield merchant_id, f"Merchant {merchant_id:05d}", rng.choice(CATEGORIES)


def accounts(config: SeedConfig) -> Iterator[tuple[int, str, str, int]]:
    for account_id in range(1, config.accounts + 1):
        balance = 0 if account_id == config.empty_account_id else INITIAL_BALANCE_CENTS
        yield account_id, f"Account holder {account_id:05d}", CURRENCY, balance


def payments(config: SeedConfig) -> Iterator[tuple[int, int, int, str, str, datetime]]:
    """Rows in insertion order: the n-th row gets payment id n."""
    rng = config._rng("payments")
    for index in range(config.payments):
        yield (
            rng.randint(1, config.accounts - 1),
            rng.randint(1, config.merchants),
            rng.randint(MIN_SEED_AMOUNT_CENTS, MAX_SEED_AMOUNT_CENTS),
            CURRENCY,
            "settled",
            BASE_TIME + index * PAYMENT_INTERVAL,
        )
