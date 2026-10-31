from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from award_wallet import __version__
from award_wallet.config import Settings
from award_wallet.db import create_db_engine, make_sessionmaker, upgrade_database
from award_wallet.security.vault import Vault
from award_wallet.services import AccountNotFound
from award_wallet.services.refresh import Refresher

from .deps import LoginRequired
from .routes import about, accounts, dashboard
from .templating import render_error

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
        title="Award Wallet",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.vault = Vault.from_config(settings.encryption_keys.get_secret_value())
    app.state.refresher = Refresher(app.state.sessionmaker, app.state.vault, screenshots_dir=settings.screenshots_dir)
    app.state.refreshed_on_open = False
    # Set by the Mac app: closes the window, which quits the app.
    app.state.quit_app = None
    app.state.available_update = None

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key.get_secret_value(),
        session_cookie="award_wallet_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
    )
    # Only answer to this computer's own address names, which blocks web pages that try to
    # reach the app through a look-alike domain (DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(dashboard.router)
    app.include_router(accounts.router)
    app.include_router(about.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(LoginRequired)
    async def not_from_the_app(request: Request, exc: LoginRequired):
        return render_error(request, 403, "Open Award Wallet from its app icon.")

    @app.exception_handler(AccountNotFound)
    async def account_not_found(request: Request, exc: AccountNotFound):
        return render_error(request, 404, "We couldn't find that program.")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return render_error(request, exc.status_code, message, headers=exc.headers)

    return app
