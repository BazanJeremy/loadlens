import pytest

from payments_api.config import Settings, parse_flag

DB = {"DATABASE_URL": "postgresql+psycopg://u:p@h/db"}


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " True "])
def test_flag_on(raw):
    assert parse_flag("X", {"X": raw}) is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", ""])
def test_flag_off(raw):
    assert parse_flag("X", {"X": raw}) is False


def test_unset_flag_is_off():
    assert parse_flag("X", {}) is False


@pytest.mark.parametrize("raw", ["yes", "on", "2", "enabled"])
def test_unrecognized_flag_is_an_error_not_a_guess(raw):
    with pytest.raises(ValueError, match="X must be one of"):
        parse_flag("X", {"X": raw})


def test_all_regressions_are_off_by_default():
    settings = Settings.from_env(DB)
    assert settings.regressions() == {"n_plus_one": False, "lock": False, "pool": False}
    assert (settings.pool_size, settings.max_overflow) == (10, 10)


def test_pool_regression_shrinks_the_pool_to_one_connection():
    settings = Settings.from_env({**DB, "SUT_REGRESSION_POOL": "1"})
    assert (settings.pool_size, settings.max_overflow) == (1, 0)


def test_database_url_is_required():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings.from_env({})
