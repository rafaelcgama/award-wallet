from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from award_wallet.models import User
from award_wallet.services import InvalidInput, users

from ..deps import SESSION_USER_KEY, CsrfProtected, DbSession, SettingsDep
from ..templating import flash, render_error, templates

router = APIRouter()

SIGNUP_CLOSED = "New sign-ups are turned off for this Award Wallet."


@router.get("/login")
def login_page(request: Request, settings: SettingsDep, next: str = "/"):
    if request.session.get(SESSION_USER_KEY):
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"next": _safe_next(next), "allow_signup": settings.allow_signup}
    )


@router.post("/login", dependencies=[CsrfProtected])
def login(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
):
    user = users.authenticate(db, email=email, password=password)
    if user is None:
        context = {
            "error": "That email and password don't match.",
            "email": email,
            "next": _safe_next(next),
            "allow_signup": settings.allow_signup,
        }
        return templates.TemplateResponse(request, "login.html", context, status_code=400)
    _start_session(request, user)
    return RedirectResponse(_safe_next(next), status_code=303)


@router.get("/register")
def register_page(request: Request, settings: SettingsDep):
    if not settings.allow_signup:
        return render_error(request, 403, SIGNUP_CLOSED)
    return templates.TemplateResponse(request, "register.html", {})


@router.post("/register", dependencies=[CsrfProtected])
def register(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    display_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
):
    if not settings.allow_signup:
        return render_error(request, 403, SIGNUP_CLOSED)
    try:
        user = users.create_user(db, email=email, password=password, display_name=display_name)
    except InvalidInput as exc:
        context = {"error": str(exc), "email": email, "display_name": display_name}
        return templates.TemplateResponse(request, "register.html", context, status_code=400)
    _start_session(request, user)
    flash(request, "Welcome! Link your first program to get started.")
    return RedirectResponse("/", status_code=303)


@router.post("/logout", dependencies=[CsrfProtected])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _start_session(request: Request, user: User) -> None:
    # Start from an empty session so nothing from before signing in carries over.
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id


def _safe_next(target: str) -> str:
    """Only allow paths on this site, so a crafted link can't send you elsewhere after sign-in."""
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"
