import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from award_wallet import __version__, updates

from ..deps import CsrfProtected, CurrentUser
from ..templating import flash, templates

router = APIRouter()

# How long the "Installing" page shows before the app quits to replace itself.
QUIT_DELAY = 1.5


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


def outside_applications(request: Request) -> str | None:
    """Where the Mac app runs from, in words, when that's not the Applications folder."""
    app = updates.running_app_bundle()
    if app is None or getattr(request.app.state, "quit_app", None) is None or updates.in_applications(app):
        return None
    return updates.where_it_runs(app)


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


def _quit_soon(request: Request) -> None:
    threading.Timer(QUIT_DELAY, request.app.state.quit_app).start()


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
            if context["update_available"]:
                request.app.state.available_update = release
        except updates.UpdateCheckFailed as exc:
            context["update_error"] = str(exc)
    return templates.TemplateResponse(request, "about.html", context)


@router.post("/update", dependencies=[CsrfProtected])
@router.post("/about/install", dependencies=[CsrfProtected])
def install_update(request: Request, user: CurrentUser):
    """One click: download the new version with a progress bar, then quit, replace and reopen."""
    app_bundle = updates.running_app_bundle()
    if not can_self_update(request) or app_bundle is None:
        flash(request, "Updates install by themselves only in the installed Mac app.", "error")
        return RedirectResponse("/about", status_code=303)
    updater: updates.Updater = request.app.state.updater
    if updater.progress().state not in ("downloading", "installing"):
        try:
            release = updates.latest_release(request.app.state.settings.update_repo)
        except updates.UpdateCheckFailed as exc:
            flash(request, str(exc), "error")
            return RedirectResponse("/about", status_code=303)
        if not updates.is_newer(release.version):
            request.app.state.available_update = None
            flash(request, "You already have the latest version.")
            return RedirectResponse("/", status_code=303)
        updater.start(release, app_bundle, when_installing=lambda: _quit_soon(request))
    return RedirectResponse("/update", status_code=303)


@router.get("/update")
def update_progress(request: Request, user: CurrentUser):
    progress = request.app.state.updater.progress()
    if progress.state == "idle":
        return RedirectResponse("/about", status_code=303)
    return templates.TemplateResponse(request, "updating.html", {"user": user, "progress": progress})


@router.get("/update/status")
def update_status(request: Request, user: CurrentUser):
    progress = request.app.state.updater.progress()
    return JSONResponse(
        {"state": progress.state, "version": progress.version, "percent": progress.percent, "error": progress.error}
    )


@router.post("/move-to-applications", dependencies=[CsrfProtected])
def move_to_applications(request: Request, user: CurrentUser):
    """Copy the app into Applications, where it can update itself, then reopen it from there."""
    app_bundle = updates.running_app_bundle()
    if outside_applications(request) is None or app_bundle is None:
        return RedirectResponse("/", status_code=303)
    target = updates.start_move(app_bundle)
    _quit_soon(request)
    if str(app_bundle).startswith("/Volumes/"):
        left_on = "dmg"
    elif "/AppTranslocation/" in str(app_bundle):
        left_on = "temporary"
    else:
        left_on = updates.where_it_runs(app_bundle)
    return templates.TemplateResponse(request, "moving.html", {"user": user, "target": target, "left_on": left_on})
