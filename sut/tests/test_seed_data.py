from itertools import islice

import pytest

from payments_api import seed_data
from payments_api.seed_data import SeedConfig

SMALL = SeedConfig(accounts=10, merchants=20, payments=500, random_seed=7)


def test_same_config_yields_the_same_rows():
    assert list(seed_data.payments(SMALL)) == list(seed_data.payments(SMALL))
    assert list(seed_data.merchants(SMALL)) == list(seed_data.merchants(SMALL))


def test_another_seed_yields_other_rows():
    other = SeedConfig(accounts=10, merchants=20, payments=500, random_seed=8)
    assert list(seed_data.payments(SMALL)) != list(seed_data.payments(other))


def test_resizing_one_table_does_not_reshuffle_another():
    more_payments = SeedConfig(accounts=10, merchants=20, payments=900, random_seed=7)
    assert list(seed_data.merchants(SMALL)) == list(seed_data.merchants(more_payments))
    assert list(seed_data.payments(SMALL)) == list(islice(seed_data.payments(more_payments), 500))


def test_empty_account_has_no_balance_and_no_payment():
    balances = {row[0]: row[3] for row in seed_data.accounts(SMALL)}
    assert balances[SMALL.empty_account_id] == 0
    others = [b for i, b in balances.items() if i != SMALL.empty_account_id]
    assert others == [seed_data.INITIAL_BALANCE_CENTS] * (SMALL.accounts - 1)
    assert all(row[0] != SMALL.empty_account_id for row in seed_data.payments(SMALL))


def test_payment_rows_stay_in_bounds_and_in_time_order():
    rows = list(seed_data.payments(SMALL))
    assert len(rows) == 500
    for account_id, merchant_id, amount, *_ in rows:
        assert 1 <= account_id < SMALL.accounts
        assert 1 <= merchant_id <= SMALL.merchants
        assert seed_data.MIN_SEED_AMOUNT_CENTS <= amount <= seed_data.MAX_SEED_AMOUNT_CENTS
    times = [row[5] for row in rows]
    assert times == sorted(times)


@pytest.mark.parametrize(
    "environ", [{"SEED_ACCOUNTS": "1"}, {"SEED_MERCHANTS": "0"}, {"SEED_PAYMENTS": "-1"}]
)
def test_invalid_seed_configuration_is_rejected(environ):
    with pytest.raises(ValueError, match="invalid seed configuration"):
        SeedConfig.from_env(environ)
