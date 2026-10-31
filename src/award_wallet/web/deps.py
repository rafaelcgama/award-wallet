import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from award_wallet.config import Settings
from award_wallet.models import User
from award_wallet.security.vault import Vault
from award_wallet.services import users

from . import csrf

SESSION_USER_KEY = "user_id"


class LoginRequired(Exception):
    pass


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as db:
        yield db


def get_vault(request: Request) -> Vault:
    return request.app.state.vault


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    user_id = request.session.get(SESSION_USER_KEY)
    user = db.get(User, user_id) if user_id else None
    if user is None and _opened_by_desktop_app(request):
        user = users.owner(db)
        request.session[SESSION_USER_KEY] = user.id
    if user is None:
        # Forget a user that no longer exists (say, after the database was reset), otherwise
        # the sign-in page would keep sending you back here.
        request.session.pop(SESSION_USER_KEY, None)
        raise LoginRequired()
    return user


def _opened_by_desktop_app(request: Request) -> bool:
    settings = request.app.state.settings
    if not (settings.single_user and settings.desktop_token):
        return False
    expected = settings.desktop_token.get_secret_value()
    return hmac.compare_digest(request.query_params.get("token", ""), expected)


def require_csrf(request: Request, csrf_token: Annotated[str, Form()] = "") -> None:
    if not csrf.is_valid(request.session, csrf_token):
        raise HTTPException(status_code=403, detail="This form has expired. Go back, reload the page and try again.")


async def get_posted_form(request: Request) -> FormData:
    """The whole posted form, for forms whose fields depend on the provider."""
    return await request.form()


DbSession = Annotated[Session, Depends(get_db)]
VaultDep = Annotated[Vault, Depends(get_vault)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PostedForm = Annotated[FormData, Depends(get_posted_form)]
CsrfProtected = Depends(require_csrf)
