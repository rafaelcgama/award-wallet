"""Settings for one launch of the app.

The keys live in settings.env in the app's data folder, created on first launch (see
desktop.py). Other values can be overridden with AW_* environment variables while developing.
"""

import os
import secrets
from datetime import date
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from award_wallet.security.vault import generate_key

KEYS_FILE_TEMPLATE = """\
# Award Wallet's keys. Keep this file private and backed up somewhere safe:
# without AW_ENCRYPTION_KEYS, the saved program logins can't be decrypted.
AW_SECRET_KEY={secret_key}
AW_ENCRYPTION_KEYS={encryption_key}
"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AW_", extra="ignore")

    database_url: str
    # Signs the window's session cookie.
    secret_key: SecretStr
    # Comma-separated "key_id:base64key" entries. The first encrypts; all of them decrypt,
    # so a new key can be put in front without losing access to older data.
    encryption_keys: SecretStr
    auto_migrate: bool = True
    # A new secret on every launch. The app's window opens /?token=... once; anything else on
    # this Mac that finds the port can't get in without it.
    desktop_token: SecretStr | None = None
    # Sign in to program websites with Chrome to fetch balances, including on every launch.
    auto_fetch: bool = False
    # Where a screenshot of the page is saved when a fetch fails, to help fix the program's reader.
    screenshots_dir: Path | None = None
    # GitHub repository whose releases "Check for Updates" looks at (owner/name).
    update_repo: str = "rafaelcgama/award-wallet"


def create_keys_file(path: Path) -> None:
    """Write fresh keys, readable by your user only. Never overwrites an existing file."""
    content = KEYS_FILE_TEMPLATE.format(
        secret_key=secrets.token_urlsafe(48),
        encryption_key=f"k{date.today():%Y%m%d}:{generate_key()}",
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
