from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from award_wallet.models import BalanceSnapshot, ExpirationLot, LoyaltyAccount
from award_wallet.providers import Provider, get_provider

from .accounts import list_accounts
from .balances import latest_snapshots


@dataclass(frozen=True)
class AccountSummary:
    account: LoyaltyAccount
    provider: Provider
    latest: BalanceSnapshot | None

    @property
    def next_expiration(self) -> ExpirationLot | None:
        if self.latest is None:
            return None
        today = date.today()
        upcoming = (lot for lot in self.latest.expirations if lot.expires_on >= today)
        return min(upcoming, key=lambda lot: lot.expires_on, default=None)


def summarize_accounts(db: Session, user_id: str) -> list[AccountSummary]:
    accounts = list_accounts(db, user_id)
    latest = latest_snapshots(db, [account.id for account in accounts])
    return [AccountSummary(account, get_provider(account.provider), latest.get(account.id)) for account in accounts]
