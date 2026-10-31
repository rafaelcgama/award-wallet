import re

import pytest
from fastapi.testclient import TestClient

from award_wallet.config import Settings
from award_wallet.security.vault import generate_key
from award_wallet.web import create_app

PASSWORD = "correct horse battery"
CSRF_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'award_wallet.db'}",
        secret_key="test-secret-key",
        encryption_keys=f"test:{generate_key()}",
        _env_file=None,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db(app, client):
    with app.state.sessionmaker() as session:
        yield session


def csrf_token(client: TestClient, path: str = "/login") -> str:
    match = CSRF_PATTERN.search(client.get(path).text)
    assert match, f"no form token on {path}"
    return match.group(1)


def post_form(client: TestClient, path: str, data: dict, *, token_from: str = "/login", **kwargs):
    return client.post(path, data={"csrf_token": csrf_token(client, token_from), **data}, **kwargs)


def register(client: TestClient, email: str = "rafael@example.com", name: str = "Rafael"):
    response = post_form(
        client,
        "/register",
        {"display_name": name, "email": email, "password": PASSWORD},
        token_from="/register",
    )
    assert response.status_code == 200, response.text
    return response


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
