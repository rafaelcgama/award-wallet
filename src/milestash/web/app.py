import logging
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from milestash import __version__, system, updates
from milestash.config import Settings
from milestash.db import create_db_engine, make_sessionmaker, upgrade_database
from milestash.security.vault import Vault
from milestash.services import AccountNotFound
from milestash.services.refresh import Refresher

from .deps import LoginRequired, TokenInAddress
from .routes import about, accounts, dashboard
from .security import LockedToTheWindow
from .templating import render_error

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
SESSION_MAX_AGE = 14 * 24 * 60 * 60


def create_app(settings: Settings) -> FastAPI:
    engine = create_db_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            upgrade_database(settings.database_url)
        yield
        engine.dispose()

    app = FastAPI(
        title="Milestash",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.vault = Vault.from_config(settings.encryption_keys.get_secret_value())
    app.state.refresher = Refresher(
        app.state.sessionmaker,
        app.state.vault,
        browser_dir=settings.browser_dir,
        screenshots_dir=settings.screenshots_dir,
    )
    app.state.refreshed_on_open = False
    # Set by the desktop app: closes the window, which quits the app.
    app.state.quit_app = None
    app.state.available_update = None
    app.state.updater = updates.Updater()

    session_key = settings.secret_key.get_secret_value()
    if settings.desktop_token:
        # Each launch signs its window's session with a new key, so a session cookie from an
        # earlier launch, or one copied off this computer, opens nothing.
        session_key += settings.desktop_token.get_secret_value()
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_key,
        session_cookie="milestash_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
    )
    # Only answer to this computer's own address names, which blocks web pages that try to
    # reach the app through a look-alike domain (DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    # Added last, so it runs before the others: a request they turn away gets the headers too.
    app.add_middleware(LockedToTheWindow)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(dashboard.router)
    app.include_router(accounts.router)
    app.include_router(about.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(LoginRequired)
    async def not_from_the_app(request: Request, exc: LoginRequired):
        return render_error(request, 403, "Open Milestash from its app icon.")

    @app.exception_handler(TokenInAddress)
    async def take_the_token_out(request: Request, exc: TokenInAddress):
        return RedirectResponse(exc.address, status_code=303)

    @app.exception_handler(AccountNotFound)
    async def account_not_found(request: Request, exc: AccountNotFound):
        return render_error(request, 404, "We couldn't find that program.")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return render_error(request, exc.status_code, message, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        # The whole story goes in the Diagnostics log, so it can be fixed; the window gets a page
        # with a way back instead of a bare "Internal Server Error".
        log.error("%s %s failed", request.method, request.url.path, exc_info=exc)
        message = (
            "Something went wrong on this page. What happened is in the Diagnostics log "
            f"(Help → Show Diagnostics in {system.file_browser()})."
        )
        try:
            return render_error(request, 500, message)
        except Exception:
            return PlainTextResponse(message, status_code=500)

    return app
