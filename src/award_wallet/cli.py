"""Command line: award-wallet init | serve | migrate | generate-key"""

import argparse
import os
import secrets
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from award_wallet.config import Settings, get_settings
from award_wallet.security.vault import generate_key

ENV_TEMPLATE = """\
# Award Wallet settings. Keep this file private, out of git, and backed up somewhere safe:
# without AW_ENCRYPTION_KEYS, the saved program logins can't be decrypted.
AW_SECRET_KEY={secret_key}
AW_ENCRYPTION_KEYS={encryption_key}

# Optional settings, shown with their defaults:
# AW_DATABASE_URL=sqlite:///data/award_wallet.db
# AW_ALLOW_SIGNUP=true
# AW_HOST=127.0.0.1
# AW_PORT=8000
"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="award-wallet", description="One dashboard for all your miles and points.")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a .env file with new secret keys")
    init.add_argument("--env-file", type=Path, default=Path(".env"))

    serve = commands.add_parser("serve", help="run the web app")
    serve.add_argument("--host", help="address to listen on (default 127.0.0.1: this computer only)")
    serve.add_argument("--port", type=int, help="port to listen on (default 8000)")

    commands.add_parser("migrate", help="bring the database up to date")
    commands.add_parser("generate-key", help="print a new encryption key, for key rotation")

    args = parser.parse_args(argv)
    handlers = {"init": _init, "serve": _serve, "migrate": _migrate, "generate-key": _generate_key}
    handlers[args.command](args)


def _new_key_entry() -> str:
    return f"k{date.today():%Y%m%d}:{generate_key()}"


def write_env_file(env_file: Path) -> None:
    """Create a settings file with fresh keys, readable by your user only. Never overwrites."""
    content = ENV_TEMPLATE.format(secret_key=secrets.token_urlsafe(48), encryption_key=_new_key_entry())
    descriptor = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)


def _init(args: argparse.Namespace) -> None:
    env_file: Path = args.env_file
    if env_file.exists():
        sys.exit(
            f"{env_file} already exists, so nothing was changed. Its keys protect your saved "
            "logins, and replacing them would make those logins unreadable."
        )
    write_env_file(env_file)
    print(f"Created {env_file} with new keys. Next, run: award-wallet serve")


def _load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        names = ", ".join(f"AW_{str(error['loc'][0]).upper()}" for error in exc.errors())
        sys.exit(f"Missing or invalid settings: {names}. Run `award-wallet init` in the project folder first.")


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from award_wallet.web import create_app

    settings = _load_settings()
    host, port = args.host or settings.host, args.port or settings.port
    try:
        app = create_app(settings)
    except ValueError as exc:
        sys.exit(f"Couldn't start: {exc}. Check AW_ENCRYPTION_KEYS in your .env file.")
    print(f"Award Wallet is running at http://{host}:{port} (press Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port)


def _migrate(args: argparse.Namespace) -> None:
    from award_wallet.db import upgrade_database

    upgrade_database(_load_settings().database_url)
    print("The database is up to date.")


def _generate_key(args: argparse.Namespace) -> None:
    print(_new_key_entry())
    print(
        "Put this first in AW_ENCRYPTION_KEYS and keep the old entries after it, separated by "
        "commas. New data uses the first key; older data stays readable with the others.",
        file=sys.stderr,
    )
