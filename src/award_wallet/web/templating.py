from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from award_wallet.models import LoyaltyAccount, SyncStatus
from award_wallet.providers import Provider

from . import csrf

TEMPLATES_DIR = Path(__file__).parent / "templates"
FLASHES_KEY = "flashes"


def flash(request: Request, message: str, category: str = "info") -> None:
    """Queue a one-time message for the next page shown."""
    request.session.setdefault(FLASHES_KEY, []).append({"message": message, "category": category})


@dataclass(frozen=True)
class StatusBadge:
    label: str
    tone: str  # "neutral", "good", "warn" or "bad"


_SYNC_BADGES = {
    SyncStatus.PENDING: StatusBadge("Not fetched yet", "neutral"),
    SyncStatus.OK: StatusBadge("Up to date", "good"),
    SyncStatus.NEEDS_LOGIN: StatusBadge("Needs your sign-in", "warn"),
    SyncStatus.ERROR: StatusBadge("Fetch failed", "bad"),
}


def account_status(
    account: LoyaltyAccount, provider: Provider, busy: bool = False, auto_fetch: bool = True
) -> StatusBadge:
    if busy:
        return StatusBadge("Refreshing…", "neutral")
    if account.credentials_encrypted is None:
        return StatusBadge("Entered by hand", "neutral")
    if not (provider.supports_fetch and auto_fetch):
        return StatusBadge("Login saved", "neutral")
    return _SYNC_BADGES[SyncStatus(account.sync_status)]


def format_number(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def format_date(value: date) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def format_datetime(value: datetime) -> str:
    local = value.astimezone()  # the computer's time zone
    return f"{format_date(local)}, {local.hour % 12 or 12}:{local:%M %p}"


def time_ago(value: datetime | None) -> str:
    if value is None:
        return "never"
    seconds = int((datetime.now(UTC) - value).total_seconds())
    for size, unit in (
        (365 * 86400, "year"),
        (30 * 86400, "month"),
        (86400, "day"),
        (3600, "hour"),
        (60, "minute"),
    ):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return "just now"


def days_until(value: date) -> str:
    days = (value - date.today()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 0:
        return "already expired"
    return f"in {days:,} days"


def _page_globals(request: Request) -> dict[str, Any]:
    return {
        "csrf_token": csrf.token_for(request.session),
        "flashes": request.session.pop(FLASHES_KEY, []),
        "auto_fetch": request.app.state.settings.auto_fetch,
        "busy": request.app.state.refresher.busy(),
    }


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_page_globals])
templates.env.filters.update(
    number=format_number,
    date=format_date,
    datetime=format_datetime,
    time_ago=time_ago,
    days_until=days_until,
)
templates.env.globals["account_status"] = account_status


def render_error(request: Request, status: int, message: str, headers: dict[str, str] | None = None):
    return templates.TemplateResponse(
        request, "error.html", {"status": status, "message": message}, status_code=status, headers=headers
    )
