from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from award_wallet.models import BalanceSnapshot, ExpirationLot, LoyaltyAccount
from award_wallet.providers import Provider, get_provider

from .accounts import list_accounts
from .balances import latest_snapshots

# How long before an expiration the program shows an alert: time enough to earn or spend some.
EXPIRES_SOON = timedelta(days=90)


def expires_soon(lot: ExpirationLot | None, today: date | None = None) -> bool:
    return lot is not None and lot.expires_on - (today or date.today()) <= EXPIRES_SOON


@dataclass(frozen=True)
class AccountSummary:
    account: LoyaltyAccount
    provider: Provider
    latest: BalanceSnapshot | None

    @property
    def checked_at(self) -> datetime | None:
        return checked_at(self.account, self.latest)

    @property
    def next_expiration(self) -> ExpirationLot | None:
        if self.latest is None:
            return None
        today = date.today()
        upcoming = (lot for lot in self.latest.expirations if lot.expires_on >= today)
        return min(upcoming, key=lambda lot: lot.expires_on, default=None)

    @property
    def expires_soon(self) -> bool:
        return expires_soon(self.next_expiration)


def checked_at(account: LoyaltyAccount, latest: BalanceSnapshot | None) -> datetime | None:
    """When the balance was last seen: the newest history entry, or a later refresh that found the
    same balance (which adds nothing to the history)."""
    moments = [moment for moment in (latest and latest.captured_at, account.last_synced_at) if moment]
    return max(moments, default=None)


def summarize_accounts(db: Session, user_id: str) -> list[AccountSummary]:
    accounts = list_accounts(db, user_id)
    latest = latest_snapshots(db, [account.id for account in accounts])
    return [AccountSummary(account, get_provider(account.provider), latest.get(account.id)) for account in accounts]
