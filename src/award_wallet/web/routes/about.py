from pathlib import Path

from fastapi import APIRouter, Request

from award_wallet import __version__, updates

from ..deps import CurrentUser
from ..templating import templates

router = APIRouter()


def _data_folder(database_url: str) -> str | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    folder = Path(database_url.removeprefix(prefix)).resolve().parent
    home = Path.home()
    return f"~/{folder.relative_to(home)}" if folder.is_relative_to(home) else str(folder)


@router.get("/about")
def about(request: Request, user: CurrentUser, check: bool = False):
    settings = request.app.state.settings
    context = {
        "user": user,
        "version": __version__,
        "data_folder": _data_folder(settings.database_url),
        "checked": check,
        "release": None,
        "update_error": None,
    }
    if check:
        try:
            release = updates.latest_release(settings.update_repo)
            context["release"] = release
            context["update_available"] = updates.is_newer(release.version)
        except updates.UpdateCheckFailed as exc:
            context["update_error"] = str(exc)
    return templates.TemplateResponse(request, "about.html", context)
