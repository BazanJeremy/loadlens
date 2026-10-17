"""HTTP API. Endpoints are synchronous: FastAPI runs them in its thread pool, and the
synchronous ORM is what lets the N+1 regression lazy-load naturally."""

from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload, sessionmaker

from payments_api.config import Settings
from payments_api.models import Account, LedgerDay, Merchant, Payment
from payments_api.schemas import (
    AccountOut,
    HealthOut,
    PaymentCreate,
    PaymentOut,
    StatementOut,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
    )
    app.state.settings = settings
    app.state.sessions = sessionmaker(engine, expire_on_commit=False)
    yield
    engine.dispose()


app = FastAPI(title="payments-api", lifespan=lifespan)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@app.get("/health")
def health(session: SessionDep, settings: SettingsDep) -> HealthOut:
    session.execute(text("SELECT 1"))
    return HealthOut(status="ok", regressions=settings.regressions())


@app.post("/payments", status_code=201)
def create_payment(body: PaymentCreate, session: SessionDep, settings: SettingsDep) -> PaymentOut:
    with session.begin():
        merchant = session.get(Merchant, body.merchant_id)
        if merchant is None:
            raise HTTPException(status_code=404, detail="merchant_not_found")

        if settings.regression_lock:
            # Regression: a running daily total updated inside every payment transaction.
            # All payments write the same row, so they queue on its lock until commit.
            upsert = insert(LedgerDay).values(
                day=func.current_date(), total_cents=body.amount_cents, payment_count=1
            )
            session.execute(
                upsert.on_conflict_do_update(
                    index_elements=[LedgerDay.day],
                    set_={
                        "total_cents": LedgerDay.total_cents + body.amount_cents,
                        "payment_count": LedgerDay.payment_count + 1,
                    },
                )
            )

        # Atomic conditional debit: no read-modify-write race between concurrent payments.
        debited = session.execute(
            update(Account)
            .where(Account.id == body.account_id, Account.balance_cents >= body.amount_cents)
            .values(balance_cents=Account.balance_cents - body.amount_cents)
            .returning(Account.currency)
        ).first()
        if debited is None:
            if session.get(Account, body.account_id) is None:
                raise HTTPException(status_code=404, detail="account_not_found")
            raise HTTPException(status_code=409, detail="insufficient_funds")

        payment = Payment(
            account_id=body.account_id,
            merchant_id=body.merchant_id,
            amount_cents=body.amount_cents,
            currency=debited.currency,
            status="settled",
        )
        payment.merchant = merchant
        session.add(payment)
        session.flush()
        return PaymentOut.model_validate(payment)


@app.get("/payments/{payment_id}")
def get_payment(payment_id: int, session: SessionDep) -> PaymentOut:
    payment = session.scalars(
        select(Payment).options(joinedload(Payment.merchant)).where(Payment.id == payment_id)
    ).one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="payment_not_found")
    return PaymentOut.model_validate(payment)


@app.get("/accounts/{account_id}/statement")
def get_statement(
    account_id: int,
    session: SessionDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[int | None, Query(gt=0)] = None,
) -> StatementOut:
    """Most recent payments first. Keyset pagination: pass `next_cursor` back as `cursor`."""
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="account_not_found")

    query = select(Payment).where(Payment.account_id == account_id)
    if cursor is not None:
        query = query.where(Payment.id < cursor)
    query = query.order_by(Payment.id.desc()).limit(limit + 1)
    if not settings.regression_n_plus_one:
        query = query.options(joinedload(Payment.merchant))
    # With the regression on, each distinct merchant below is lazy-loaded by its own query.

    rows = session.scalars(query).all()
    items = rows[:limit]
    return StatementOut(
        account=AccountOut.model_validate(account),
        items=[PaymentOut.model_validate(p) for p in items],
        next_cursor=items[-1].id if len(rows) > limit else None,
    )
