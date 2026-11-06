from collections.abc import Iterable, Sequence
from datetime import date, datetime

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
    """Put a balance in the program's history, which keeps changes rather than every look: the
    same balance as last time adds nothing, and a change on a day that already has one replaces it,
    so each day has at most one entry. Returns the history's newest entry."""
    if not 0 <= balance < MAX_BALANCE:
        raise InvalidInput("Enter a balance of zero or more.")
    for lot in expirations:
        if lot.amount is not None and not 0 < lot.amount <= balance:
            raise InvalidInput("The expiring amount must be more than zero and at most the balance.")

    when = captured_at or utcnow()
    lots = sorted((lot.expires_on, lot.amount or 0) for lot in expirations)
    newest = latest_snapshots(db, [account.id]).get(account.id)
    if newest is not None and newest.balance == balance and _lots(newest) == lots:
        db.commit()
        return newest
    entry = newest if newest is not None and local_day(newest.captured_at) == local_day(when) else None
    if entry is None:
        entry = BalanceSnapshot(account_id=account.id)
        db.add(entry)
    entry.balance = balance
    entry.unit = get_provider(account.provider).unit
    entry.source = source
    entry.captured_at = when
    entry.expirations = [ExpirationLot(expires_on=lot.expires_on, amount=lot.amount) for lot in expirations]
    db.commit()
    return entry


def local_day(moment: datetime) -> date:
    """The date on this computer's calendar."""
    return moment.astimezone().date()


def _lots(snapshot: BalanceSnapshot) -> list[tuple[date, int]]:
    return sorted((lot.expires_on, lot.amount or 0) for lot in snapshot.expirations)


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
    """The balance's changes, newest first: one entry per day at most, the day's last, and only
    when it differs from the entry before. (Versions before 0.7 kept every refresh.)"""
    query = (
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account.id)
        .order_by(BalanceSnapshot.captured_at.desc(), BalanceSnapshot.id.desc())
    )
    days: list[BalanceSnapshot] = []
    for snapshot in db.scalars(query):
        if not days or local_day(snapshot.captured_at) != local_day(days[-1].captured_at):
            days.append(snapshot)
    # A day counts only if its balance changed from the day before it; the first day always does.
    changes = [
        day
        for day, before in zip(days, days[1:], strict=False)
        if (day.balance, _lots(day)) != (before.balance, _lots(before))
    ]
    return [*changes, *days[-1:]][:limit]
