"""Settings, read from AW_* environment variables or a .env file in the current folder."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AW_", env_file=".env", extra="ignore")

    # SQLite for local use; point this at Postgres (postgresql+psycopg://...) when hosting.
    database_url: str = "sqlite:///data/award_wallet.db"
    # Signs the session cookie.
    secret_key: SecretStr
    # Comma-separated "key_id:base64key" entries. The first encrypts; all of them decrypt,
    # so a new key can be put in front without losing access to older data.
    encryption_keys: SecretStr
    allow_signup: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    # Turn on when serving over HTTPS so the session cookie is never sent in the clear.
    secure_cookies: bool = False
    auto_migrate: bool = True
    # The Mac app: one person, so open straight to their points with no sign-in screen.
    single_user: bool = False
    # Set by the Mac app on each launch. Its window opens /?token=... once; anything else on
    # this computer that finds the port can't get in without it.
    desktop_token: SecretStr | None = None
    # Sign in to program websites with Chrome to fetch balances, including on every app launch.
    auto_fetch: bool = False
    # Where a screenshot of the page is saved when a fetch fails, to help fix the program's reader.
    screenshots_dir: Path | None = None
    # GitHub repository whose releases "Check for Updates" looks at (owner/name).
    update_repo: str = "rafaelcgama/award-wallet"


@lru_cache
def get_settings() -> Settings:
    return Settings()
