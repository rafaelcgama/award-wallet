"""Database tables.

Every row of user data hangs off a User, and every query in services/ filters by the owning
user, so one installation can serve several people without them seeing each other's data.
"""

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores datetimes in UTC and always returns them timezone-aware (SQLite drops the zone)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are ambiguous; pass a timezone-aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SyncStatus(StrEnum):
    PENDING = "pending"  # not fetched with the current login yet
    OK = "ok"
    NEEDS_LOGIN = "needs_login"  # login rejected, or a security code is needed
    ERROR = "error"


class BalanceSource(StrEnum):
    MANUAL = "manual"
    SYNC = "sync"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    accounts: Mapped[list["LoyaltyAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class LoyaltyAccount(Base):
    """One program a user tracks, such as their United MileagePlus account."""

    __tablename__ = "loyalty_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Key of the provider in award_wallet.providers, e.g. "united".
    provider: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(100))
    # Login for the program's website, encrypted by the Vault. None when tracked by hand.
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Browser cookies saved by a provider's fetcher so it can skip the login, and its
    # security code, next time. Also encrypted.
    session_state_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    sync_status: Mapped[str] = mapped_column(String(20), default=SyncStatus.PENDING)
    sync_message: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="accounts")
    snapshots: Mapped[list["BalanceSnapshot"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class BalanceSnapshot(Base):
    """A balance as read at one moment. Kept as history; the newest one is the current balance."""

    __tablename__ = "balance_snapshots"
    __table_args__ = (Index("ix_balance_snapshots_account_captured", "account_id", "captured_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("loyalty_accounts.id", ondelete="CASCADE"))
    balance: Mapped[int] = mapped_column(BigInteger)
    unit: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    account: Mapped[LoyaltyAccount] = relationship(back_populates="snapshots")
    expirations: Mapped[list["ExpirationLot"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ExpirationLot.expires_on",
    )


class ExpirationLot(Base):
    """Points from a snapshot that expire on a date. amount None means the whole balance."""

    __tablename__ = "expiration_lots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("balance_snapshots.id", ondelete="CASCADE"), index=True)
    expires_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[int | None] = mapped_column(BigInteger)

    snapshot: Mapped[BalanceSnapshot] = relationship(back_populates="expirations")
