import io
import json
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from award_wallet import __version__, updates
from award_wallet.web import create_app


class _window:
    """The app window, already signed in with its launch token."""

    def __init__(self, settings):
        desktop = settings.model_copy(update={"desktop_token": SecretStr("t")})
        self.client = TestClient(create_app(desktop), base_url="http://127.0.0.1")

    def __enter__(self):
        self.client.__enter__()
        self.client.get("/?token=t")
        return self.client

    def __exit__(self, *exc):
        return self.client.__exit__(*exc)


def test_version_matches_package_metadata():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == __version__


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("v0.3.0", "0.2.0", True),
        ("0.2.1", "0.2.0", True),
        ("0.2", "0.2.0", False),
        ("v0.1.9", "0.2.0", False),
        ("1.0.0-beta", "0.9", True),
    ],
)
def test_version_comparison(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


def test_about_page_shows_version(settings):
    with _window(settings) as window:
        page = window.get("/about")
        assert page.status_code == 200
        assert f"Version {__version__}" in page.text
        assert "Check for updates" in page.text


def _fake_github(monkeypatch, payload=None, error=None):
    def urlopen(request, timeout, context):
        if error:
            raise error
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", urlopen)


def test_newer_release_offers_download(settings, monkeypatch):
    _fake_github(
        monkeypatch,
        {
            "tag_name": "v99.0.0",
            "html_url": "https://github.com/x/y/releases/v99.0.0",
            "assets": [{"name": "Award Wallet.dmg", "browser_download_url": "https://example.com/aw.dmg"}],
        },
    )
    with _window(settings) as window:
        page = window.get("/about?check=1")
        assert "Version 99.0.0 is available" in page.text
        assert "https://example.com/aw.dmg" in page.text


def test_current_release_says_up_to_date(settings, monkeypatch):
    _fake_github(monkeypatch, {"tag_name": f"v{__version__}", "html_url": "", "assets": []})
    with _window(settings) as window:
        assert "You have the latest version" in window.get("/about?check=1").text


def test_failed_check_is_explained(settings, monkeypatch):
    _fake_github(monkeypatch, error=urllib.error.URLError("offline"))
    with _window(settings) as window:
        assert "Couldn&#39;t reach GitHub" in window.get("/about?check=1").text
    _fake_github(monkeypatch, error=urllib.error.HTTPError("u", 404, "nf", {}, None))
    with _window(settings) as window:
        assert "No published releases" in window.get("/about?check=1").text


def test_installed_app_installs_updates_itself(settings, monkeypatch, tmp_path):
    release = updates.Release("99.0.0", "https://github.com/x/y", "https://example.com/aw.dmg")
    monkeypatch.setattr(updates, "latest_release", lambda repo: release)
    monkeypatch.setattr(updates, "running_app_bundle", lambda: tmp_path / "Award Wallet.app")
    started, quit_calls = [], []
    monkeypatch.setattr(updates, "start_install", lambda r, app: started.append((r.version, app.name)))
    monkeypatch.setattr(
        "award_wallet.web.routes.about.threading.Timer", lambda delay, fn: type("T", (), {"start": lambda self: fn()})()
    )
    with _window(settings) as window:
        window.app.state.quit_app = lambda: quit_calls.append(True)
        about = window.get("/about?check=1").text
        assert "Install version 99.0.0" in about
        token = about.split('name="csrf_token" value="')[1].split('"')[0]
        page = window.post("/about/install", data={"csrf_token": token})
        assert "Installing version 99.0.0" in page.text
    assert started == [("99.0.0", "Award Wallet.app")]
    assert quit_calls == [True]


def test_web_version_only_links_to_the_download(settings, monkeypatch):
    release = updates.Release("99.0.0", "https://github.com/x/y", "https://example.com/aw.dmg")
    monkeypatch.setattr(updates, "latest_release", lambda repo: release)
    with _window(settings) as window:
        about = window.get("/about?check=1").text
        assert "Install version" not in about
        assert "https://example.com/aw.dmg" in about


def test_installer_waits_swaps_and_reopens(tmp_path):
    script = updates.installer_script(tmp_path / "u.dmg", Path("/Applications/Award Wallet.app"), 4242)
    assert "kill -0 4242" in script
    assert "'/Applications/Award Wallet.app'" in script
    assert script.rstrip().endswith("open '/Applications/Award Wallet.app'")
