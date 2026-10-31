import stat

from fastapi.testclient import TestClient

from award_wallet.desktop import desktop_settings
from award_wallet.web import create_app

from conftest import link, post_form


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
