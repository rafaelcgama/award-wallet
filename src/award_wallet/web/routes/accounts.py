import json
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from award_wallet.models import BalanceSource, LoyaltyAccount, User
from award_wallet.providers import Expiration, Provider, UnknownProvider, all_providers, get_provider
from award_wallet.services import InvalidInput, accounts, balances
from award_wallet.services.dashboard import checked_at
from award_wallet.services.refresh import can_fetch

from ..deps import CsrfProtected, CurrentUser, DbSession, PostedForm, VaultDep
from ..templating import flash, templates

router = APIRouter(prefix="/accounts")

# How long the sign-in page's question "anything new?" waits for an answer, in seconds.
STATUS_WAIT = 10
# The most a batch of clicks and keys from the sign-in page may take up, in characters.
MAX_INPUT = 20_000


@router.get("/new")
def new_account_page(request: Request, user: CurrentUser, provider: str | None = None):
    if provider is None:
        return templates.TemplateResponse(request, "account_new.html", {"user": user, "providers": all_providers()})
    return templates.TemplateResponse(
        request, "account_form.html", {"user": user, "provider": _provider_or_404(provider)}
    )


@router.post("/new", dependencies=[CsrfProtected])
def link_account(request: Request, db: DbSession, vault: VaultDep, user: CurrentUser, form: PostedForm):
    provider = _provider_or_404(str(form.get("provider", "")))
    label = str(form.get("label", ""))
    try:
        account = accounts.link_account(
            db,
            vault,
            user_id=user.id,
            provider_key=provider.key,
            label=label,
            credentials=_posted_credentials(form, provider),
        )
    except InvalidInput as exc:
        context = {"user": user, "provider": provider, "label": label, "error": str(exc)}
        return templates.TemplateResponse(request, "account_form.html", context, status_code=400)
    flash(request, f"{provider.name} is linked.")
    _fetch_out_of_sight(request, account)
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.get("/{account_id}")
def account_page(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    return _render_account(request, db, user, account)


@router.post("/{account_id}/balance", dependencies=[CsrfProtected])
def enter_balance(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    account_id: str,
    balance: Annotated[str, Form()] = "",
    expiring_amount: Annotated[str, Form()] = "",
    expires_on: Annotated[str, Form()] = "",
):
    account = accounts.get_account(db, user.id, account_id)
    try:
        balances.record_balance(
            db,
            account,
            balance=_parse_whole_number(balance, "balance"),
            source=BalanceSource.MANUAL,
            expirations=_parse_expiration(expiring_amount, expires_on),
        )
    except InvalidInput as exc:
        posted = {"balance": balance, "expiring_amount": expiring_amount, "expires_on": expires_on}
        return _render_account(request, db, user, account, status_code=400, balance_error=str(exc), posted=posted)
    flash(request, "Balance saved.")
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.post("/{account_id}/login", dependencies=[CsrfProtected])
def update_login(
    request: Request,
    db: DbSession,
    vault: VaultDep,
    user: CurrentUser,
    account_id: str,
    form: PostedForm,
):
    account = accounts.get_account(db, user.id, account_id)
    provider = get_provider(account.provider)
    credentials = _posted_credentials(form, provider)
    before = accounts.read_credentials(vault, account) or {}
    try:
        if not any(credentials.values()):
            raise InvalidInput("Fill in the login fields to save a new login.")
        accounts.update_credentials(db, vault, account, credentials)
    except InvalidInput as exc:
        return _render_account(request, db, user, account, status_code=400, login_error=str(exc))
    # A new password keeps Chrome's memory of this Mac; someone else's login starts fresh.
    if any(
        before.get(field.name) != credentials.get(field.name)
        for field in provider.credential_fields
        if not field.secret
    ):
        request.app.state.refresher.forget_browser(account.id)
    flash(request, "Login saved.")
    _fetch_out_of_sight(request, account)
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.post("/{account_id}/sign-in", dependencies=[CsrfProtected])
def sign_in(request: Request, db: DbSession, user: CurrentUser, account_id: str, form: PostedForm):
    """Start signing in, shown in the window: the program's page from the hidden Chrome that
    refreshes it, where you finish what the site asks for."""
    account = accounts.get_account(db, user.id, account_id)
    # From a card on the dashboard, the dashboard is where you go back to.
    from_dashboard = form.get("back") == "dashboard"
    refresher = request.app.state.refresher
    if not (request.app.state.settings.auto_fetch and can_fetch(account)):
        return RedirectResponse(_back(account, from_dashboard), status_code=303)
    if refresher.view(account.id) is None and refresher.sign_in(account) is None:
        flash(request, f"{get_provider(account.provider).name} is refreshing right now. Click Sign in once it's done.")
        return RedirectResponse(_back(account, from_dashboard), status_code=303)
    page = f"/accounts/{account.id}/sign-in" + ("?back=dashboard" if from_dashboard else "")
    return RedirectResponse(page, status_code=303)


@router.get("/{account_id}/sign-in")
def sign_in_page(request: Request, db: DbSession, user: CurrentUser, account_id: str, back: str = ""):
    account = accounts.get_account(db, user.id, account_id)
    view = request.app.state.refresher.view(account.id)
    if view is None:
        return RedirectResponse(f"/accounts/{account.id}", status_code=303)
    context = {
        "user": user,
        "account": account,
        "provider": get_provider(account.provider),
        "note": view.note,
        "from_dashboard": back == "dashboard",
        "back": _back(account, back == "dashboard"),
    }
    return templates.TemplateResponse(request, "sign_in.html", context)


@router.get("/{account_id}/sign-in/status")
def sign_in_status(request: Request, db: DbSession, user: CurrentUser, account_id: str, after: int = -1):
    """What the sign-in shows now, once there's a newer picture of the page than `after`."""
    account = accounts.get_account(db, user.id, account_id)
    db.close()  # nothing more from the database while this waits
    view = request.app.state.refresher.view(account.id)
    if view is None:
        return JSONResponse({"state": "gone"})
    return JSONResponse(view.status(after=after, timeout=STATUS_WAIT))


@router.get("/{account_id}/sign-in/picture")
def sign_in_picture(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    """The newest picture of the page you're signing in on."""
    account = accounts.get_account(db, user.id, account_id)
    view = request.app.state.refresher.view(account.id)
    picture = view.picture() if view else None
    if picture is None:
        raise HTTPException(status_code=404, detail="Nothing to show.")
    return Response(picture, media_type="image/jpeg")


@router.post("/{account_id}/sign-in/input", dependencies=[CsrfProtected])
def sign_in_input(
    request: Request, db: DbSession, user: CurrentUser, account_id: str, events: Annotated[str, Form()] = ""
):
    """Your clicks and keys on the picture of the page, for the page itself."""
    account = accounts.get_account(db, user.id, account_id)
    view = request.app.state.refresher.view(account.id)
    if view is None:
        raise HTTPException(status_code=409, detail="This sign-in has ended.")
    try:
        if len(events) > MAX_INPUT:
            raise ValueError("Too much at once.")
        view.send(json.loads(events))
    except ValueError as exc:  # json's own errors are ValueErrors too
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return Response(status_code=204)


@router.post("/{account_id}/sign-in/stop", dependencies=[CsrfProtected])
def stop_sign_in(request: Request, db: DbSession, user: CurrentUser, account_id: str, form: PostedForm):
    account = accounts.get_account(db, user.id, account_id)
    request.app.state.refresher.stop_sign_in(account.id)
    return RedirectResponse(_back(account, form.get("back") == "dashboard"), status_code=303)


@router.post("/{account_id}/refresh", dependencies=[CsrfProtected])
def refresh(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    if request.app.state.settings.auto_fetch:
        request.app.state.refresher.refresh_one(account)
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


def _fetch_out_of_sight(request: Request, account: LoyaltyAccount) -> None:
    """Sign in and fetch the balance, out of sight. If the site wants you (a code, say), the
    program shows a Sign in button, which shows you the site's page in the app's window."""
    if request.app.state.settings.auto_fetch:
        request.app.state.refresher.refresh_one(account)


def _back(account: LoyaltyAccount, from_dashboard: bool) -> str:
    return "/" if from_dashboard else f"/accounts/{account.id}"


@router.post("/{account_id}/login/remove", dependencies=[CsrfProtected])
def remove_login(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    accounts.remove_credentials(db, account)
    request.app.state.refresher.forget_browser(account.id)
    flash(request, "Login removed. You can keep entering this balance by hand.")
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.post("/{account_id}/delete", dependencies=[CsrfProtected])
def delete_account(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    label = account.label
    accounts.delete_account(db, account)
    request.app.state.refresher.forget_browser(account_id)
    flash(request, f"Removed {label}.")
    return RedirectResponse("/", status_code=303)


def _render_account(
    request: Request,
    db: Session,
    user: User,
    account: LoyaltyAccount,
    *,
    status_code: int = 200,
    **extra: Any,
):
    history = balances.balance_history(db, account)
    newest = balances.latest_snapshots(db, [account.id]).get(account.id)
    context = {
        "user": user,
        "account": account,
        "checked_at": checked_at(account, newest),
        "provider": get_provider(account.provider),
        "history": history,
        "latest": newest,
        "posted": {},
        **extra,
    }
    return templates.TemplateResponse(request, "account_detail.html", context, status_code=status_code)


def _provider_or_404(key: str) -> Provider:
    try:
        return get_provider(key)
    except UnknownProvider:
        raise HTTPException(status_code=404, detail="Award Wallet doesn't support that program yet.") from None


def _posted_credentials(form: FormData, provider: Provider) -> dict[str, str]:
    return {field.name: str(form.get(f"credential_{field.name}", "")) for field in provider.credential_fields}


def _parse_whole_number(raw: str, what: str) -> int:
    cleaned = raw.strip().replace(",", "").replace(" ", "")
    if not (cleaned.isascii() and cleaned.isdigit()):
        raise InvalidInput(f"Enter the {what} as a whole number, like 52,300.")
    return int(cleaned)


def _parse_expiration(amount_raw: str, date_raw: str) -> list[Expiration]:
    amount_raw, date_raw = amount_raw.strip(), date_raw.strip()
    if not date_raw:
        if amount_raw:
            raise InvalidInput("Add the date those points expire.")
        return []
    try:
        expires_on = date.fromisoformat(date_raw)
    except ValueError:
        raise InvalidInput("Enter the expiration date as YYYY-MM-DD.") from None
    if expires_on < date.today():
        raise InvalidInput("That expiration date has already passed.")
    amount = _parse_whole_number(amount_raw, "expiring amount") if amount_raw else None
    return [Expiration(expires_on=expires_on, amount=amount)]
