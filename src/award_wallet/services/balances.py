from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from award_wallet.models import BalanceSnapshot, BalanceSource, ExpirationLot, LoyaltyAccount, utcnow
from award_wallet.providers import Expiration, get_provider

from .errors import InvalidInput

MAX_BALANCE = 10**12


def record_balance(
    db: Session,
    account: LoyaltyAccount,
    *,
    balance: int,
    source: BalanceSource,
    expirations: Sequence[Expiration] = (),
    captured_at: datetime | None = None,
) -> BalanceSnapshot:
    if not 0 <= balance < MAX_BALANCE:
        raise InvalidInput("Enter a balance of zero or more.")
    for lot in expirations:
        if lot.amount is not None and not 0 < lot.amount <= balance:
            raise InvalidInput("The expiring amount must be more than zero and at most the balance.")

    snapshot = BalanceSnapshot(
        account_id=account.id,
        balance=balance,
        unit=get_provider(account.provider).unit,
        source=source,
        captured_at=captured_at or utcnow(),
        expirations=[ExpirationLot(expires_on=lot.expires_on, amount=lot.amount) for lot in expirations],
    )
    db.add(snapshot)
    db.commit()
    return snapshot


def latest_snapshots(db: Session, account_ids: Iterable[str]) -> dict[str, BalanceSnapshot]:
    """The newest snapshot of each account, in one query however long the history gets."""
    ids = list(account_ids)
    if not ids:
        return {}
    ranked = (
        select(
            BalanceSnapshot.id,
            func.row_number()
            .over(
                partition_by=BalanceSnapshot.account_id,
                order_by=(BalanceSnapshot.captured_at.desc(), BalanceSnapshot.id.desc()),
            )
            .label("position"),
        )
        .where(BalanceSnapshot.account_id.in_(ids))
        .subquery()
    )
    newest = select(BalanceSnapshot).join(ranked, ranked.c.id == BalanceSnapshot.id).where(ranked.c.position == 1)
    return {snapshot.account_id: snapshot for snapshot in db.scalars(newest)}


def balance_history(db: Session, account: LoyaltyAccount, *, limit: int = 30) -> list[BalanceSnapshot]:
    query = (
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account.id)
        .order_by(BalanceSnapshot.captured_at.desc(), BalanceSnapshot.id.desc())
        .limit(limit)
    )
    return list(db.scalars(query))
