"""Request and response bodies."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_PAYMENT_CENTS = 1_000_000


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    account_id: int = Field(gt=0)
    merchant_id: int = Field(gt=0)
    amount_cents: int = Field(gt=0, le=MAX_PAYMENT_CENTS)


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    merchant: MerchantOut
    amount_cents: int
    currency: str
    status: str
    created_at: datetime


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_name: str
    currency: str
    balance_cents: int


class StatementOut(BaseModel):
    account: AccountOut
    items: list[PaymentOut]
    next_cursor: int | None


class HealthOut(BaseModel):
    status: str
    regressions: dict[str, bool]
