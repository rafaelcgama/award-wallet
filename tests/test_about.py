import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from award_wallet import __version__, updates
from award_wallet.web import create_app


class _window:
    """The app window, already signed in with its launch token."""

    def __init__(self, settings):
        desktop = settings.model_copy(update={"single_user": True, "desktop_token": SecretStr("t")})
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
