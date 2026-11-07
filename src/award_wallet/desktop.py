r"""The app on a Mac or a Windows PC: runs the web app invisibly and shows it in its own window.

Data and keys live where each system keeps apps' data: ~/Library/Application Support/Award Wallet
on a Mac, %LOCALAPPDATA%\Award Wallet on Windows.
"""

import argparse
import html
import logging
import logging.handlers
import os
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

import uvicorn

from award_wallet import __version__, system
from award_wallet.config import Settings, create_keys_file

APP_NAME = "Award Wallet"
KEYS_FILE = "settings.env"
DATABASE_FILE = "award_wallet.db"
# Logs and failed-fetch screenshots: safe to send for troubleshooting, unlike the keys and
# database next to it.
DIAGNOSTICS_DIR = "Diagnostics"
# Each program's Chrome profile, which keeps its sign-in.
BROWSER_DIR = "Browser"
LOG_FILE = "award-wallet.log"


def data_dir() -> Path:
    if system.on_mac():
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if system.on_windows():
        # Local, not Roaming: each program's Chrome profile belongs to this PC.
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    return Path.home() / ".local" / "share" / "award-wallet"


def desktop_settings(directory: Path, token: str) -> Settings:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Only you can open the folder with your logins, balances and keys, even if an older version
    # left it open to others on this Mac. (On Windows, your own AppData folder already is.)
    directory.chmod(0o700)
    keys_file = directory / KEYS_FILE
    if not keys_file.exists():
        create_keys_file(keys_file)
    return Settings(
        _env_file=keys_file,
        database_url=f"sqlite:///{(directory / DATABASE_FILE).as_posix()}",
        auto_fetch=True,
        browser_dir=directory / BROWSER_DIR,
        screenshots_dir=directory / DIAGNOSTICS_DIR / "screenshots",
        desktop_token=token,
    )


def start_logging(directory: Path) -> Path:
    """Keep a small rolling log of what the app does, for troubleshooting a program's fetch."""
    folder = directory / DIAGNOSTICS_DIR
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        folder / LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Libraries stay quiet unless something goes wrong.
    for noisy in ("uvicorn", "uvicorn.access", "sqlalchemy", "alembic", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return folder


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


def show_folder(folder: Path) -> None:
    """Open a folder in Finder, or File Explorer on Windows."""
    folder.mkdir(parents=True, exist_ok=True)
    if system.on_windows():
        os.startfile(str(folder))
    else:
        subprocess.run(["open", str(folder)], check=False)


def app_menus(window, base_url: str) -> list:
    """Menus like other apps: on a Mac, Check for Updates in the app menu, and About and updates
    in Help; on Windows, the same Help menu at the top of the window."""
    from webview.menu import Menu, MenuAction

    def check_for_updates() -> None:
        window.load_url(f"{base_url}/about?check=1")

    def show_about() -> None:
        window.load_url(f"{base_url}/about")

    def show_diagnostics() -> None:
        show_folder(data_dir() / DIAGNOSTICS_DIR)

    help_menu = Menu(
        "Help",
        [
            MenuAction(f"About {APP_NAME}", show_about),
            MenuAction("Check for Updates…", check_for_updates),
            MenuAction(f"Show Diagnostics in {system.file_browser()}", show_diagnostics),
        ],
    )
    if system.on_windows():
        return [help_menu]
    # "__app__" adds to the Award Wallet menu, under its standard About and Quit items.
    return [Menu("__app__", [MenuAction("Check for Updates…", check_for_updates)]), help_menu]


def _show_problem(heading: str, text: str) -> None:
    """A small window that says why the app can't open; text is HTML."""
    import webview

    webview.create_window(
        APP_NAME,
        html=(
            "<body style='font:15px -apple-system,\"Segoe UI\",sans-serif;padding:32px;line-height:1.5'>"
            f"<h2>{html.escape(heading)}</h2><p>{text}</p></body>"
        ),
        width=560,
        height=260,
    )
    webview.start()


def _show_startup_error() -> None:
    folder = data_dir() / DIAGNOSTICS_DIR
    _show_problem(
        "Award Wallet couldn't start",
        f"The details are in the log file in <code>{html.escape(str(folder))}</code>. "
        "Send it over and it'll get fixed. Your data is safe.",
    )


def window_engine() -> str:
    """What draws the app's window on Windows: "edgechromium" is Microsoft Edge WebView2, which
    comes with Windows 11 and an up-to-date Windows 10. Without it, Windows would use Internet
    Explorer's old engine, which the app's pages don't work in."""
    from webview.platforms import winforms

    return winforms.renderer


def self_test(report: Path) -> bool:
    """Check a build without a screen or your data: the server starts on a new, empty data folder
    (keys, database, its updates, the pages and their files), and so does Chrome, as a refresh
    would start it. Writes "ok" and what it saw to report, or "failed" and why. Never raises: a
    packaged Windows app would show the error in a box nobody is there to close."""
    import tempfile
    import traceback
    import urllib.request
    from http.cookiejar import CookieJar

    seen = []
    try:
        with tempfile.TemporaryDirectory(prefix="award-wallet-self-test-", ignore_cleanup_errors=True) as folder:
            token = secrets.token_urlsafe(16)
            server, thread, url = start_server(desktop_settings(Path(folder) / "data", token))
            try:
                # The launch link signs the window in with a cookie, then shows the points.
                window = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
                with window.open(f"{url}/?token={token}", timeout=30) as page:
                    if "Your points" not in page.read().decode("utf-8"):
                        raise RuntimeError("The first page didn't show the points")
                with window.open(f"{url}/static/style.css", timeout=30) as style:
                    style.read()
                seen.append("Pages: ok")
            finally:
                server.should_exit = True
                thread.join(timeout=5)

            from award_wallet.fetching import browser_launcher

            playwright, context = browser_launcher(Path(folder) / "profile")
            try:
                page = context.pages[0] if context.pages else context.new_page()
                seen.append(f"Chrome: {page.evaluate('navigator.userAgent')}")
            finally:
                context.close()
                playwright.stop()
            if system.on_windows():
                # The window's parts load (.NET, through pythonnet), without opening one.
                seen.append(f"Window: {window_engine()}")
    except Exception:
        report.write_text("failed\n" + "\n".join(seen) + "\n" + traceback.format_exc(), encoding="utf-8")
        return False
    report.write_text("ok\n" + "\n".join(seen) + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    # For checking a build without a screen: start the server, print its address, keep running.
    parser.add_argument("--no-window", action="store_true", help=argparse.SUPPRESS)
    # Checks that the app can start Chrome for fetching: prints its version and quits.
    parser.add_argument("--check-browser", action="store_true", help=argparse.SUPPRESS)
    # Checks a build end to end without touching your data, and writes how it went to a file
    # (a Windows app has nowhere to print): see self_test.
    parser.add_argument("--self-test", metavar="REPORT", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.self_test:
        self_test(args.self_test)
        return

    if args.check_browser:
        import tempfile

        from award_wallet.fetching import browser_launcher

        with tempfile.TemporaryDirectory() as profile:
            playwright, context = browser_launcher(Path(profile))
            page = context.pages[0] if context.pages else context.new_page()
            print(f"Chrome is ready: {page.evaluate('navigator.userAgent')}", flush=True)
            context.close()
            playwright.stop()
        return

    if system.on_windows() and not args.no_window:
        from award_wallet import windows

        # One copy at a time, as on a Mac: opening it again shows the window that's already open.
        if not windows.claim_single_instance():
            windows.show_running_copy(APP_NAME)
            return
        if window_engine() != "edgechromium":
            _show_problem(
                "Award Wallet needs Microsoft Edge WebView2",
                "Windows 11 and an up-to-date Windows 10 come with it. Get it from Microsoft at "
                "<code>developer.microsoft.com/microsoft-edge/webview2</code>, then open Award Wallet again.",
            )
            return

    # Everything the app writes (its database, logs, screenshots and each program's Chrome
    # profile) is readable by you alone.
    os.umask(0o077)
    start_logging(data_dir())
    logging.getLogger(__name__).info("Award Wallet %s starting", __version__)
    token = secrets.token_urlsafe(32)
    try:
        server, thread, url = start_server(desktop_settings(data_dir(), token))
    except Exception:
        logging.getLogger(__name__).exception("Award Wallet couldn't start")
        if args.no_window:
            raise
        _show_startup_error()
        return
    start_url = f"{url}/?token={token}"
    try:
        if args.no_window:
            print(start_url, flush=True)
            thread.join()
        else:
            import webview

            # The window shows the app's own pages, never files from this computer.
            webview.settings["ALLOW_FILE_URLS"] = False
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
