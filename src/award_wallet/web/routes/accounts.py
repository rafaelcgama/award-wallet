from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from award_wallet.models import BalanceSource, LoyaltyAccount, User
from award_wallet.providers import Expiration, Provider, UnknownProvider, all_providers, get_provider
from award_wallet.services import InvalidInput, accounts, balances

from ..deps import CsrfProtected, CurrentUser, DbSession, PostedForm, VaultDep
from ..templating import flash, templates

router = APIRouter(prefix="/accounts")


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
    _start_sign_in(request, account)
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
    credentials = _posted_credentials(form, get_provider(account.provider))
    try:
        if not any(credentials.values()):
            raise InvalidInput("Fill in the login fields to save a new login.")
        accounts.update_credentials(db, vault, account, credentials)
    except InvalidInput as exc:
        return _render_account(request, db, user, account, status_code=400, login_error=str(exc))
    flash(request, "Login saved.")
    _start_sign_in(request, account)
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.post("/{account_id}/sign-in", dependencies=[CsrfProtected])
def sign_in(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    _start_sign_in(request, account)
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.post("/{account_id}/refresh", dependencies=[CsrfProtected])
def refresh(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    if request.app.state.settings.auto_fetch:
        request.app.state.refresher.refresh_one(account)
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


def _start_sign_in(request: Request, account: LoyaltyAccount) -> None:
    """Open the program's site in a Chrome window to sign in and fetch the balance."""
    if request.app.state.settings.auto_fetch and request.app.state.refresher.sign_in(account):
        name = get_provider(account.provider).name
        flash(request, f"A Chrome window is opening to sign in to {name}. Enter the security code there if asked.")


@router.post("/{account_id}/login/remove", dependencies=[CsrfProtected])
def remove_login(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    accounts.remove_credentials(db, account)
    flash(request, "Login removed. You can keep entering this balance by hand.")
    return RedirectResponse(f"/accounts/{account.id}", status_code=303)


@router.post("/{account_id}/delete", dependencies=[CsrfProtected])
def delete_account(request: Request, db: DbSession, user: CurrentUser, account_id: str):
    account = accounts.get_account(db, user.id, account_id)
    label = account.label
    accounts.delete_account(db, account)
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
    context = {
        "user": user,
        "account": account,
        "provider": get_provider(account.provider),
        "history": history,
        "latest": history[0] if history else None,
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
