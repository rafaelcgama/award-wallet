import re

import pytest
from fastapi.testclient import TestClient

from award_wallet.config import Settings
from award_wallet.security.vault import generate_key
from award_wallet.web import create_app

CSRF_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


LAUNCH_TOKEN = "launch-token"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'award_wallet.db'}",
        secret_key="test-secret-key",
        encryption_keys=f"test:{generate_key()}",
        desktop_token=LAUNCH_TOKEN,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


def open_window(app) -> TestClient:
    """The app's window: a client on 127.0.0.1, signed in by opening the launch URL."""
    window = TestClient(app, base_url="http://127.0.0.1")
    window.__enter__()
    window.get(f"/?token={LAUNCH_TOKEN}")
    return window


@pytest.fixture
def client(app):
    window = open_window(app)
    yield window
    window.__exit__(None, None, None)


@pytest.fixture
def db(app, client):
    with app.state.sessionmaker() as session:
        yield session


def csrf_token(client: TestClient, path: str = "/") -> str:
    match = CSRF_PATTERN.search(client.get(path).text)
    assert match, f"no form token on {path}"
    return match.group(1)


def post_form(client: TestClient, path: str, data: dict, *, token_from: str = "/", **kwargs):
    return client.post(path, data={"csrf_token": csrf_token(client, token_from), **data}, **kwargs)


def link(client: TestClient, provider: str = "united", **fields) -> str:
    """Link a program and return its account id."""
    response = post_form(
        client,
        "/accounts/new",
        {"provider": provider, **fields},
        token_from=f"/accounts/new?provider={provider}",
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].rsplit("/", 1)[-1]
