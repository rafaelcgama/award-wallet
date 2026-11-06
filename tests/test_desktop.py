import re
import stat
from pathlib import Path

from fastapi.testclient import TestClient

from award_wallet.desktop import desktop_settings
from award_wallet.web import create_app

from conftest import csrf_token, link, post_form


def test_first_launch_creates_private_keys_and_reuses_them(tmp_path):
    first = desktop_settings(tmp_path / "app", "token-1")
    keys_file = tmp_path / "app" / "settings.env"
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
        cookie = window.cookies.get("award_wallet_session")
        assert cookie and window.get("/").status_code == 200
    with TestClient(create_app(desktop_settings(tmp_path, "token-2")), base_url="http://127.0.0.1") as later:
        assert later.get("/", headers={"Cookie": f"award_wallet_session={cookie}"}).status_code == 403


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
    templates = Path(__file__).parents[1] / "src" / "award_wallet" / "web" / "templates"
    for template in templates.glob("*.html"):
        text = template.read_text()
        assert not re.search(r"<script(?![^>]*\bsrc=)", text), template.name
        assert not re.search(r"\son[a-z]+=|\sstyle=|javascript:", text), template.name


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

    from award_wallet.desktop import start_logging

    folder = start_logging(tmp_path)
    try:
        logging.getLogger("award_wallet.test").info("hello from the test")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "hello from the test" in (folder / "award-wallet.log").read_text()
        assert folder.name == "Diagnostics"
    finally:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "baseFilename", "").startswith(str(folder)):
                root.removeHandler(handler)
                handler.close()
