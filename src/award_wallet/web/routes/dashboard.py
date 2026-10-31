from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from award_wallet.services.dashboard import summarize_accounts
from award_wallet.services.refresh import can_fetch

from ..deps import CsrfProtected, CurrentUser, DbSession
from ..templating import flash, templates
from .about import check_in_background

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: DbSession, user: CurrentUser):
    state = request.app.state
    if state.settings.auto_fetch and not state.refreshed_on_open:
        # Fresh balances every time the app opens.
        state.refreshed_on_open = True
        state.refresher.refresh_all(db, user.id)
        check_in_background(request.app)
    summaries = summarize_accounts(db, user.id)
    can_refresh = state.settings.auto_fetch and any(can_fetch(s.account) for s in summaries)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "summaries": summaries,
            "can_refresh": can_refresh,
            "available_update": getattr(state, "available_update", None),
        },
    )


@router.post("/refresh", dependencies=[CsrfProtected])
def refresh_now(request: Request, db: DbSession, user: CurrentUser):
    refresher = request.app.state.refresher
    if request.app.state.settings.auto_fetch:
        refresher.refresh_all(db, user.id)
        waiting = [s.account for s in summarize_accounts(db, user.id) if s.account.sync_status == "needs_login"]
        if waiting:
            names = ", ".join(account.label for account in waiting)
            flash(request, f"{names} need{'s' if len(waiting) == 1 else ''} you to sign in first. Open it to continue.")
    return RedirectResponse("/", status_code=303)
