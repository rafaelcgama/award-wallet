import stat

from fastapi.testclient import TestClient
from pydantic import SecretStr

from award_wallet.desktop import desktop_settings
from award_wallet.web import create_app

from conftest import link, post_form, register


def test_first_launch_creates_private_keys_and_reuses_them(tmp_path):
    first = desktop_settings(tmp_path / "app", "token-1")
    keys_file = tmp_path / "app" / "settings.env"
    assert stat.S_IMODE(keys_file.stat().st_mode) == 0o600
    second = desktop_settings(tmp_path / "app", "token-2")
    assert first.encryption_keys == second.encryption_keys
    assert second.single_user and not second.allow_signup


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


def test_existing_account_is_reused(tmp_path, settings):
    # Data carried over from the Terminal version keeps its account.
    with TestClient(create_app(settings)) as browser:
        register(browser, "rafael@example.com", "Rafael")
    desktop = settings.model_copy(update={"single_user": True, "desktop_token": SecretStr("t")})
    with TestClient(create_app(desktop), base_url="http://127.0.0.1") as window:
        assert "Rafael" not in window.get("/?token=t").text  # name lives in the hidden header
        post_form(window, "/accounts/new", {"provider": "chase"}, token_from="/accounts/new?provider=chase")
        assert "Ultimate Rewards" in window.get("/").text
