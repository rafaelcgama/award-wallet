from fastapi import APIRouter, Request

from award_wallet.services.dashboard import summarize_accounts

from ..deps import CurrentUser, DbSession
from ..templating import templates

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: DbSession, user: CurrentUser):
    summaries = summarize_accounts(db, user.id)
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "summaries": summaries})
