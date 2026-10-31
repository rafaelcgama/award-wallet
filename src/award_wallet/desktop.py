"""The Mac app: runs the web app invisibly and shows it in its own window.

Data and keys live in ~/Library/Application Support/Award Wallet, the usual place for Mac apps.
"""

import argparse
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from award_wallet.cli import write_env_file
from award_wallet.config import Settings

APP_NAME = "Award Wallet"
KEYS_FILE = "settings.env"
DATABASE_FILE = "award_wallet.db"


def data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / "award-wallet"


def desktop_settings(directory: Path, token: str) -> Settings:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    keys_file = directory / KEYS_FILE
    if not keys_file.exists():
        write_env_file(keys_file)
    return Settings(
        _env_file=keys_file,
        database_url=f"sqlite:///{directory / DATABASE_FILE}",
        single_user=True,
        allow_signup=False,
        auto_fetch=True,
        screenshots_dir=directory / "screenshots",
        desktop_token=token,
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_server(settings: Settings) -> tuple[uvicorn.Server, threading.Thread, str]:
    from award_wallet.web import create_app

    port = _free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="award-wallet-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Award Wallet's server didn't start")
        time.sleep(0.05)
    return server, thread, f"http://127.0.0.1:{port}"


def app_menus(window, base_url: str) -> list:
    """Menus like other Mac apps: Check for Updates in the app menu, About and updates in Help."""
    from webview.menu import Menu, MenuAction

    def check_for_updates() -> None:
        window.load_url(f"{base_url}/about?check=1")

    def show_about() -> None:
        window.load_url(f"{base_url}/about")

    return [
        # "__app__" adds to the Award Wallet menu, under its standard About and Quit items.
        Menu("__app__", [MenuAction("Check for Updates…", check_for_updates)]),
        Menu(
            "Help",
            [MenuAction(f"About {APP_NAME}", show_about), MenuAction("Check for Updates…", check_for_updates)],
        ),
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    # For checking a build without a screen: start the server, print its address, keep running.
    parser.add_argument("--no-window", action="store_true", help=argparse.SUPPRESS)
    # Checks that the app can start Chrome for fetching: prints its version and quits.
    parser.add_argument("--check-browser", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.check_browser:
        from award_wallet.fetching import browser_launcher

        playwright, browser = browser_launcher(headless=True)
        print(f"Chrome {browser.version} is ready", flush=True)
        browser.close()
        playwright.stop()
        return

    token = secrets.token_urlsafe(32)
    server, thread, url = start_server(desktop_settings(data_dir(), token))
    start_url = f"{url}/?token={token}"
    try:
        if args.no_window:
            print(start_url, flush=True)
            thread.join()
        else:
            import webview

            window = webview.create_window(APP_NAME, start_url, width=1120, height=820, min_size=(420, 560))
            server.config.app.state.quit_app = window.destroy
            # Closing the window quits the app: nothing keeps running and there's no menu bar icon.
            # Cookies are kept between launches so the window stays signed in.
            webview.start(menu=app_menus(window, url), private_mode=False, storage_path=str(data_dir() / "webview"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
