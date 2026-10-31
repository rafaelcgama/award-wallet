import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from award_wallet import __version__, updates

from ..deps import CsrfProtected, CurrentUser
from ..templating import flash, templates

router = APIRouter()


def _data_folder(database_url: str) -> str | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    folder = Path(database_url.removeprefix(prefix)).resolve().parent
    home = Path.home()
    return f"~/{folder.relative_to(home)}" if folder.is_relative_to(home) else str(folder)


def can_self_update(request: Request) -> bool:
    """Only the installed Mac app can replace itself."""
    return getattr(request.app.state, "quit_app", None) is not None and updates.running_app_bundle() is not None


def check_in_background(app) -> None:
    """Look for a newer release once per launch, without slowing the window down."""

    def check() -> None:
        try:
            release = updates.latest_release(app.state.settings.update_repo)
        except updates.UpdateCheckFailed:
            return
        if updates.is_newer(release.version):
            app.state.available_update = release

    threading.Thread(target=check, name="award-wallet-update-check", daemon=True).start()


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
        "can_install": can_self_update(request),
    }
    if check:
        try:
            release = updates.latest_release(settings.update_repo)
            context["release"] = release
            context["update_available"] = updates.is_newer(release.version)
        except updates.UpdateCheckFailed as exc:
            context["update_error"] = str(exc)
    return templates.TemplateResponse(request, "about.html", context)


@router.post("/about/install", dependencies=[CsrfProtected])
def install_update(request: Request, user: CurrentUser):
    app_bundle = updates.running_app_bundle()
    if not can_self_update(request) or app_bundle is None:
        flash(request, "Updates install by themselves only in the installed Mac app.", "error")
        return RedirectResponse("/about", status_code=303)
    try:
        release = updates.latest_release(request.app.state.settings.update_repo)
        if not updates.is_newer(release.version):
            flash(request, "You already have the latest version.")
            return RedirectResponse("/about", status_code=303)
        updates.start_install(release, app_bundle)
    except updates.UpdateCheckFailed as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/about", status_code=303)
    # Quit shortly after this page shows; the installer swaps the app and reopens it.
    threading.Timer(1.5, request.app.state.quit_app).start()
    return templates.TemplateResponse(request, "updating.html", {"user": user, "release": release})
