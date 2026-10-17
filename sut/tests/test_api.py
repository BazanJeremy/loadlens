"""The API must behave identically with every regression switched on: regressions change
performance, never results. CI runs this file once per regression mode."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import islice

import httpx
import pytest

from payments_api import seed_data
from payments_api.config import parse_flag

ACCOUNT = 1
MERCHANT = 1


def balance_of(api, account_id):
    response = api.get(f"/accounts/{account_id}/statement", params={"limit": 1})
    response.raise_for_status()
    return response.json()["account"]["balance_cents"]


# --- health -------------------------------------------------------------------------------


def test_health_reports_the_regressions_this_run_was_started_with(api):
    body = api.get("/health").json()
    expected = {
        "n_plus_one": parse_flag("SUT_REGRESSION_N_PLUS_ONE", os.environ),
        "lock": parse_flag("SUT_REGRESSION_LOCK", os.environ),
        "pool": parse_flag("SUT_REGRESSION_POOL", os.environ),
    }
    assert body == {"status": "ok", "regressions": expected}, (
        "the SUT was not started with the SUT_REGRESSION_* values of this test run"
    )


# --- seed -----------------------------------------------------------------------------------


def test_seeded_payments_match_the_deterministic_generator(api, seed_config):
    for payment_id, row in enumerate(islice(seed_data.payments(seed_config), 3), start=1):
        account_id, merchant_id, amount, currency, status, created_at = row
        body = api.get(f"/payments/{payment_id}").json()
        assert body["account_id"] == account_id
        assert body["merchant"] == {"id": merchant_id, "name": f"Merchant {merchant_id:05d}"}
        assert (body["amount_cents"], body["currency"], body["status"]) == (
            amount,
            currency,
            status,
        )
        assert datetime.fromisoformat(body["created_at"]) == created_at


# --- POST /payments -------------------------------------------------------------------------


def test_create_payment_debits_the_account_and_is_readable(api):
    before = balance_of(api, ACCOUNT)
    response = api.post(
        "/payments", json={"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": 1234}
    )
    assert response.status_code == 201
    created = response.json()
    assert created["account_id"] == ACCOUNT
    assert created["merchant"]["id"] == MERCHANT
    assert (created["amount_cents"], created["currency"], created["status"]) == (
        1234,
        "EUR",
        "settled",
    )
    assert balance_of(api, ACCOUNT) == before - 1234
    assert api.get(f"/payments/{created['id']}").json() == created


def test_concurrent_payments_on_one_account_lose_no_update(api):
    before = balance_of(api, ACCOUNT)

    def pay(_):
        with httpx.Client(base_url=api.base_url, timeout=60) as client:
            return client.post(
                "/payments",
                json={"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": 100},
            )

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(pay, range(20)))
    assert [r.status_code for r in responses] == [201] * 20
    assert len({r.json()["id"] for r in responses}) == 20
    assert balance_of(api, ACCOUNT) == before - 20 * 100


def test_insufficient_funds_is_a_conflict_and_debits_nothing(api, seed_config):
    empty = seed_config.empty_account_id
    response = api.post(
        "/payments", json={"account_id": empty, "merchant_id": MERCHANT, "amount_cents": 1}
    )
    assert (response.status_code, response.json()) == (409, {"detail": "insufficient_funds"})
    assert balance_of(api, empty) == 0


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"account_id": 999_999, "merchant_id": MERCHANT, "amount_cents": 1}, "account_not_found"),
        ({"account_id": ACCOUNT, "merchant_id": 999_999, "amount_cents": 1}, "merchant_not_found"),
    ],
)
def test_unknown_account_or_merchant_is_not_found(api, body, detail):
    response = api.post("/payments", json=body)
    assert (response.status_code, response.json()) == (404, {"detail": detail})


@pytest.mark.parametrize(
    "body",
    [
        {"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": 0},
        {"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": -5},
        {"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": 1_000_001},
        {"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": "10"},
        {"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": 1.5},
        {"account_id": ACCOUNT, "merchant_id": MERCHANT},
        {"account_id": ACCOUNT, "merchant_id": MERCHANT, "amount_cents": 1, "extra": True},
    ],
    ids=["zero", "negative", "over-max", "string", "float", "missing", "extra-field"],
)
def test_invalid_payment_body_is_rejected_and_debits_nothing(api, body):
    before = balance_of(api, ACCOUNT)
    assert api.post("/payments", json=body).status_code == 422
    assert balance_of(api, ACCOUNT) == before


# --- GET /payments/{id} ---------------------------------------------------------------------


def test_unknown_payment_is_not_found(api):
    response = api.get("/payments/999999999")
    assert (response.status_code, response.json()) == (404, {"detail": "payment_not_found"})


def test_non_integer_payment_id_is_rejected(api):
    assert api.get("/payments/abc").status_code == 422


# --- GET /accounts/{id}/statement -----------------------------------------------------------


def test_statement_pages_cover_the_history_once_newest_first(api):
    seen, cursor = [], None
    while True:
        params = {"limit": 40} | ({"cursor": cursor} if cursor else {})
        page = api.get(f"/accounts/{ACCOUNT}/statement", params=params).json()
        assert page["account"]["id"] == ACCOUNT
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert len(page["items"]) == 40
        assert cursor == page["items"][-1]["id"]
    assert seen == sorted(seen, reverse=True)
    assert len(seen) == len(set(seen)) > 40


def test_statement_items_carry_their_merchant(api):
    items = api.get(f"/accounts/{ACCOUNT}/statement").json()["items"]
    assert len(items) == 50
    for item in items:
        merchant = item["merchant"]
        assert merchant["name"] == f"Merchant {merchant['id']:05d}"


def test_statement_of_an_account_without_payments_is_empty(api, seed_config):
    page = api.get(f"/accounts/{seed_config.empty_account_id}/statement").json()
    assert (page["items"], page["next_cursor"]) == ([], None)


def test_statement_of_unknown_account_is_not_found(api):
    response = api.get("/accounts/999999/statement")
    assert (response.status_code, response.json()) == (404, {"detail": "account_not_found"})


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"cursor": 0}])
def test_statement_rejects_out_of_range_paging(api, params):
    assert api.get(f"/accounts/{ACCOUNT}/statement", params=params).status_code == 422
