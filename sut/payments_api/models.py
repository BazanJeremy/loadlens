"""Database schema."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40))


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    owner_name: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3))
    balance_cents: Mapped[int] = mapped_column(BigInteger)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_account_id_id", "account_id", "id"),)
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Lazy by default: the nominal statement query asks for a join explicitly; the N+1
    # regression simply omits it.
    merchant: Mapped[Merchant] = relationship(lazy="select")


class LedgerDay(Base):
    """Running daily total. Only written by the SUT_REGRESSION_LOCK code path."""

    __tablename__ = "ledger_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    total_cents: Mapped[int] = mapped_column(BigInteger)
    payment_count: Mapped[int] = mapped_column(BigInteger)
