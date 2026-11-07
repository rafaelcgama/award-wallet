"""Settings for one launch of the app.

The keys live in settings.env in the app's data folder, created on first launch (see
desktop.py). Other values can be overridden with MILESTASH_* environment variables while developing.
Milestash was called Award Wallet until 0.14.0: the keys it wrote are named AW_*, and still work.
"""

import os
import secrets
from datetime import date
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from milestash.security.vault import generate_key

KEYS_FILE_TEMPLATE = """\
# Milestash's keys. Keep this file private and backed up somewhere safe:
# without MILESTASH_ENCRYPTION_KEYS, the saved program logins can't be decrypted.
MILESTASH_SECRET_KEY={secret_key}
MILESTASH_ENCRYPTION_KEYS={encryption_key}
"""


class Settings(BaseSettings):
    # validate_by_name: the app and the tests pass the keys by these names too.
    model_config = SettingsConfigDict(env_prefix="MILESTASH_", extra="ignore", validate_by_name=True)

    database_url: str
    # Signs the window's session cookie.
    secret_key: SecretStr = Field(validation_alias=AliasChoices("MILESTASH_SECRET_KEY", "AW_SECRET_KEY"))
    # Comma-separated "key_id:base64key" entries. The first encrypts; all of them decrypt,
    # so a new key can be put in front without losing access to older data.
    encryption_keys: SecretStr = Field(validation_alias=AliasChoices("MILESTASH_ENCRYPTION_KEYS", "AW_ENCRYPTION_KEYS"))
    auto_migrate: bool = True
    # A new secret on every launch. The app's window opens /?token=... once; anything else on
    # this computer that finds the port can't get in without it.
    desktop_token: SecretStr | None = None
    # Sign in to program websites with Chrome to fetch balances, including on every launch.
    auto_fetch: bool = False
    # Where each program's Chrome profile lives: its cookies, and the site's memory of this computer.
    browser_dir: Path | None = None
    # Where a screenshot of the page is saved when a fetch fails, to help fix the program's reader.
    screenshots_dir: Path | None = None
    # GitHub repository whose releases "Check for Updates" looks at (owner/name).
    update_repo: str = "rafaelcgama/milestash"


def create_keys_file(path: Path) -> None:
    """Write fresh keys, readable by your user only. Never overwrites an existing file."""
    content = KEYS_FILE_TEMPLATE.format(
        secret_key=secrets.token_urlsafe(48),
        encryption_key=f"k{date.today():%Y%m%d}:{generate_key()}",
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
