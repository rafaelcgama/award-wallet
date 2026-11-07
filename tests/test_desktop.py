import contextlib
import re
import shutil
import sqlite3
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from milestash.desktop import desktop_settings
from milestash.web import create_app

from conftest import csrf_token, link, post_form


def test_first_launch_creates_private_keys_and_reuses_them(tmp_path):
    first = desktop_settings(tmp_path / "app", "token-1")
    keys_file = tmp_path / "app" / "settings.env"
    if sys.platform != "win32":
        # On Windows, the AppData folder it's in is yours alone already.
        assert stat.S_IMODE(keys_file.stat().st_mode) == 0o600
    second = desktop_settings(tmp_path / "app", "token-2")
    assert first.encryption_keys == second.encryption_keys
    assert second.auto_fetch


def test_app_window_opens_straight_to_the_points(tmp_path):
    settings = desktop_settings(tmp_path, "launch-token")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as window:
        page = window.get("/?token=launch-token")
        assert page.status_code == 200
        assert "Your points" in page.text
        assert "Sign out" not in page.text
        # The session sticks, so later pages don't need the token.
        account_id = link(window, "united")
        assert window.get(f"/accounts/{account_id}").status_code == 200


def test_other_programs_on_the_mac_cannot_get_in(tmp_path):
    settings = desktop_settings(tmp_path, "launch-token")
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as intruder:
        assert intruder.get("/").status_code == 403
        assert intruder.get("/?token=guess").status_code == 403
    with TestClient(app, base_url="http://evil.example") as rebinding:
        assert rebinding.get("/?token=launch-token").status_code == 400


def test_the_launch_token_comes_out_of_the_address(tmp_path):
    settings = desktop_settings(tmp_path, "launch-token")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as window:
        page = window.get("/about?token=launch-token&check=0")
        assert [step.status_code for step in page.history] == [303]
        assert page.status_code == 200 and page.url.path == "/about" and str(page.url).endswith("?check=0")


def test_a_session_from_an_earlier_launch_opens_nothing(tmp_path):
    with TestClient(create_app(desktop_settings(tmp_path, "token-1")), base_url="http://127.0.0.1") as window:
        window.get("/?token=token-1")
        cookie = window.cookies.get("milestash_session")
        assert cookie and window.get("/").status_code == 200
    with TestClient(create_app(desktop_settings(tmp_path, "token-2")), base_url="http://127.0.0.1") as later:
        assert later.get("/", headers={"Cookie": f"milestash_session={cookie}"}).status_code == 403


def test_pages_lock_themselves_to_the_window(tmp_path):
    settings = desktop_settings(tmp_path, "launch-token")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as window:
        page = window.get("/?token=launch-token")
        policy = page.headers["content-security-policy"]
        assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy and "unsafe" not in policy
        assert page.headers["x-frame-options"] == "DENY" and page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["referrer-policy"] == "same-origin"
        # Pages show your balances, so no copy is kept on disk; the app's own files can be.
        assert page.headers["cache-control"] == "no-store"
        assert window.get("/static/style.css").headers.get("cache-control") != "no-store"
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as intruder:
        assert "content-security-policy" in intruder.get("/").headers


def test_other_websites_cannot_send_the_window_anything(tmp_path):
    settings = desktop_settings(tmp_path, "launch-token")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as window:
        window.get("/?token=launch-token")
        account_id = link(window, "united")
        form = {"csrf_token": csrf_token(window, f"/accounts/{account_id}")}
        delete = f"/accounts/{account_id}/delete"
        # Even a page that somehow knew the form's token is turned away.
        for elsewhere in (
            {"Origin": "http://evil.example"},
            {"Origin": "http://127.0.0.1:8080"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            assert window.post(delete, data=form, headers=elsewhere).status_code == 403
        assert window.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert window.get(f"/accounts/{account_id}").status_code == 200
        # The window's own form goes through.
        own = {"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"}
        assert window.post(delete, data=form, headers=own, follow_redirects=False).status_code == 303


def test_pages_run_only_the_apps_own_scripts():
    # Their content security policy blocks code written into a page, so none may creep back in.
    templates = Path(__file__).parents[1] / "src" / "milestash" / "web" / "templates"
    for template in templates.glob("*.html"):
        text = template.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", text), template.name
        assert not re.search(r"\son[a-z]+=|\sstyle=|javascript:", text), template.name


@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps each person's AppData folder to them")
def test_the_data_folder_is_yours_alone(tmp_path):
    folder = tmp_path / "app"
    folder.mkdir()
    folder.chmod(0o755)
    desktop_settings(folder, "launch-token")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_programs_carry_over_between_launches(tmp_path):
    first_launch = desktop_settings(tmp_path, "token-1")
    with TestClient(create_app(first_launch), base_url="http://127.0.0.1") as window:
        window.get("/?token=token-1")
        post_form(window, "/accounts/new", {"provider": "chase"}, token_from="/accounts/new?provider=chase")

    # A new launch gets a new token; the old one no longer opens the window.
    second_launch = desktop_settings(tmp_path, "token-2")
    with TestClient(create_app(second_launch), base_url="http://127.0.0.1") as window:
        assert window.get("/?token=token-1").status_code == 403
        assert "Ultimate Rewards" in window.get("/?token=token-2").text


def test_log_file_is_kept_in_the_diagnostics_folder(tmp_path):
    import logging

    from milestash.desktop import start_logging

    folder = start_logging(tmp_path)
    try:
        logging.getLogger("milestash.test").info("hello from the test")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "hello from the test" in (folder / "milestash.log").read_text(encoding="utf-8")
        assert folder.name == "Diagnostics"
    finally:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "baseFilename", "").startswith(str(folder)):
                root.removeHandler(handler)
                handler.close()


def test_check_browser_starts_chrome_and_says_so(monkeypatch, capsys):
    from milestash import desktop, fetching

    started = []

    class Page:
        def evaluate(self, script):
            return "Mozilla/5.0 Chrome/150.0"

    class Context:
        pages = [Page()]

        def close(self):
            started.append("closed")

    class Playwright:
        def stop(self):
            started.append("stopped")

    def launcher(profile):
        started.append(profile.is_dir())
        return Playwright(), Context()

    monkeypatch.setattr(fetching, "browser_launcher", launcher)
    desktop.main(["--check-browser"])
    assert "Chrome is ready: Mozilla/5.0 Chrome/150.0" in capsys.readouterr().out
    assert started == [True, "closed", "stopped"]


def test_each_computer_keeps_the_data_where_its_apps_keep_theirs(monkeypatch, tmp_path):
    from milestash import desktop, system

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(system, "on_mac", lambda: False)
    monkeypatch.setattr(system, "on_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert desktop.data_dir() == tmp_path / "AppData" / "Local" / "Milestash"
    monkeypatch.setattr(system, "on_windows", lambda: False)
    monkeypatch.setattr(system, "on_mac", lambda: True)
    assert desktop.data_dir() == tmp_path / "Library" / "Application Support" / "Milestash"


# Milestash was called Award Wallet until 0.14.0 -------------------------------------------------


# Award Wallet only ever ran on a Mac (and Windows won't rename files a test still has open).
award_wallet_mac = pytest.mark.skipif(sys.platform == "win32", reason="Award Wallet was a Mac app")


@pytest.fixture
def mac_home(monkeypatch, tmp_path):
    """A Mac's Application Support folder, in a home of the test's own."""
    from milestash import system

    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(system, "on_windows", lambda: False)
    monkeypatch.setattr(system, "on_mac", lambda: True)
    return tmp_path / "home" / "Library" / "Application Support"


def _award_wallet_folder(folder: Path):
    """A data folder the way Award Wallet left it, with United linked: its keys named AW_*, its
    database and log, and United's Chrome profile."""
    settings = desktop_settings(folder, "token-1")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as window:
        window.get("/?token=token-1")
        account_id = link(window, "united")
    keys = folder / "settings.env"
    keys.write_text(keys.read_text().replace("MILESTASH_", "AW_").replace("Milestash", "Award Wallet"))
    for path in folder.glob("milestash.db*"):
        path.rename(folder / path.name.replace("milestash", "award_wallet"))
    (folder / "Diagnostics").mkdir()
    (folder / "Diagnostics" / "award-wallet.log").write_text("Award Wallet 0.13.0 starting\n")
    (folder / "Browser" / account_id).mkdir(parents=True)
    (folder / "Browser" / account_id / "Cookies").write_text("signed in")
    return settings, account_id


@award_wallet_mac
def test_an_update_from_award_wallet_carries_everything_over(mac_home):
    from milestash import desktop

    old = mac_home / "Award Wallet"
    before, account_id = _award_wallet_folder(old)
    # Until it has the new name, the app keeps using the old folder, so nothing goes missing.
    assert desktop.data_dir() == old
    desktop.move_old_data()
    folder = mac_home / "Milestash"
    assert desktop.data_dir() == folder and not old.exists()
    contents = ["Browser", "Diagnostics", "milestash.db", "settings.env"]
    assert sorted(path.name for path in folder.iterdir()) == contents
    assert (folder / "Diagnostics" / "milestash.log").read_text() == "Award Wallet 0.13.0 starting\n"
    assert (folder / "Browser" / account_id / "Cookies").read_text() == "signed in"
    # The keys Award Wallet wrote still open the saved logins.
    after = desktop_settings(desktop.data_dir(), "token-2")
    assert (after.secret_key, after.encryption_keys) == (before.secret_key, before.encryption_keys)
    assert after.database_url.endswith("/Milestash/milestash.db")
    with TestClient(create_app(after), base_url="http://127.0.0.1") as window:
        window.get("/?token=token-2")
        assert window.get(f"/accounts/{account_id}").status_code == 200
    # It only happens once.
    desktop.move_old_data()
    assert sorted(path.name for path in folder.iterdir()) == contents


@award_wallet_mac
def test_award_wallet_data_that_cant_be_renamed_is_used_where_it_is(mac_home, monkeypatch):
    from milestash import desktop

    old = mac_home / "Award Wallet"
    before, account_id = _award_wallet_folder(old)

    def refuse(path, target):
        raise PermissionError(target)

    monkeypatch.setattr(Path, "rename", refuse)
    desktop.move_old_data()
    assert desktop.data_dir() == old
    after = desktop_settings(desktop.data_dir(), "token-2")
    assert after.database_url.endswith("/Award Wallet/award_wallet.db")
    assert after.encryption_keys == before.encryption_keys


def test_a_new_computer_starts_with_the_new_name(mac_home):
    from milestash import desktop

    desktop.move_old_data()
    assert desktop.data_dir() == mac_home / "Milestash" and not mac_home.exists()


def test_the_database_keeps_what_only_its_journal_held(tmp_path):
    from milestash import desktop

    folder = tmp_path / "Award Wallet"
    folder.mkdir()
    writer = sqlite3.connect(folder / "award_wallet.db")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE balance (miles INTEGER)")
    writer.execute("INSERT INTO balance VALUES (120000)")
    writer.commit()
    # As the app leaves it if it stops before folding its journal in: the balance is only there.
    left = tmp_path / "left"
    shutil.copytree(folder, left)
    writer.close()
    assert (left / "award_wallet.db-wal").exists()
    desktop._rename_database(left)
    assert "milestash.db" in [path.name for path in left.iterdir()]
    assert not [path.name for path in left.iterdir() if path.name.startswith("award_wallet.db")]
    with contextlib.closing(sqlite3.connect(left / "milestash.db")) as reader:
        assert reader.execute("SELECT miles FROM balance").fetchall() == [(120000,)]


def test_the_mac_app_tries_to_take_its_new_name_once(monkeypatch, tmp_path):
    from milestash import desktop, updates

    app = tmp_path / "Applications" / "Award Wallet.app"
    renamed = []
    monkeypatch.setattr(updates, "app_to_rename", lambda: app)
    monkeypatch.setattr(updates, "start_rename", renamed.append)
    assert desktop.rename_old_app(tmp_path / "data")
    assert renamed == [app]
    # If it didn't work, it opens under the old name from then on.
    assert not desktop.rename_old_app(tmp_path / "data")
    assert renamed == [app]
    monkeypatch.setattr(updates, "app_to_rename", lambda: None)
    assert not desktop.rename_old_app(tmp_path / "other")


def test_the_server_starts_without_a_console(monkeypatch, tmp_path):
    # A Windows app has no console: Python gives it no stdout or stderr.
    from milestash import desktop

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    server, thread, url = desktop.start_server(desktop_settings(tmp_path, "token"))
    server.should_exit = True
    thread.join(timeout=5)
    assert url.startswith("http://127.0.0.1:")


def test_the_database_address_works_with_windows_folders(tmp_path):
    settings = desktop_settings(tmp_path / "Milestash", "launch-token")
    assert settings.database_url == f"sqlite:///{(tmp_path / 'Milestash' / 'milestash.db').as_posix()}"
    assert "\\" not in settings.database_url


@pytest.mark.parametrize(
    ("on_windows", "menus", "diagnostics"),
    [(True, ["Help"], "Show Diagnostics in File Explorer"), (False, ["__app__", "Help"], "Show Diagnostics in Finder")],
)
def test_help_is_where_each_computer_keeps_it(monkeypatch, on_windows, menus, diagnostics):
    # On Windows, the Help menu is at the top of the window; on a Mac, in the menu bar, with Check
    # for Updates in the Milestash menu too.
    pytest.importorskip("webview.menu")
    from milestash import desktop, system

    monkeypatch.setattr(system, "on_windows", lambda: on_windows)
    shown = desktop.app_menus(window=None, base_url="http://127.0.0.1:1")
    assert [menu.title for menu in shown] == menus
    assert [item.title for item in shown[-1].items] == ["About Milestash", "Check for Updates…", diagnostics]


def test_opening_the_app_again_on_windows_shows_the_open_one(monkeypatch):
    from milestash import desktop, system, windows

    shown = []
    monkeypatch.setattr(system, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "claim_single_instance", lambda: False)
    monkeypatch.setattr(windows, "show_running_copy", shown.append)
    monkeypatch.setattr(desktop, "start_server", lambda settings: pytest.fail("a second copy started"))
    desktop.main([])
    assert shown == ["Milestash"]


def test_without_webview2_windows_says_what_to_get(monkeypatch):
    from milestash import desktop, system, windows

    problems = []
    monkeypatch.setattr(system, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "claim_single_instance", lambda: True)
    monkeypatch.setattr(desktop, "window_engine", lambda: "mshtml")
    monkeypatch.setattr(desktop, "_show_problem", lambda heading, text: problems.append(heading))
    monkeypatch.setattr(desktop, "start_server", lambda settings: pytest.fail("the app started"))
    desktop.main([])
    assert problems == ["Milestash needs Microsoft Edge WebView2"]


class _Chrome:
    """Stands in for the hidden Chrome the self-test starts."""

    def __init__(self, started: list):
        self.started = started

    def __call__(self, profile):
        self.started.append(profile)
        chrome = self

        class Page:
            def evaluate(self, script):
                return "Mozilla/5.0 Chrome/150.0.0.0"

        class Context:
            pages = [Page()]

            def close(self):
                chrome.started.append("closed")

        class Playwright:
            def stop(self):
                chrome.started.append("stopped")

        return Playwright(), Context()


def test_the_self_test_checks_a_build_without_your_data(monkeypatch, tmp_path):
    from milestash import desktop, fetching, system

    started = []
    monkeypatch.setattr(fetching, "browser_launcher", _Chrome(started))
    monkeypatch.setattr(system, "on_windows", lambda: False)
    monkeypatch.setattr(desktop, "data_dir", lambda: pytest.fail("the self-test touched your data"))
    report = tmp_path / "report.txt"
    assert desktop.main(["--self-test", str(report)]) is None
    assert report.read_text(encoding="utf-8") == "ok\nPages: ok\nChrome: Mozilla/5.0 Chrome/150.0.0.0\n"
    assert started[1:] == ["closed", "stopped"]


def test_a_self_test_that_fails_says_why_and_never_raises(monkeypatch, tmp_path):
    from milestash import desktop, fetching

    def no_chrome(profile):
        raise fetching.ChromeMissing("Google Chrome isn't installed")

    monkeypatch.setattr(fetching, "browser_launcher", no_chrome)
    report = tmp_path / "report.txt"
    assert desktop.self_test(report) is False
    text = report.read_text(encoding="utf-8")
    assert text.startswith("failed\nPages: ok\n") and "Google Chrome isn't installed" in text
