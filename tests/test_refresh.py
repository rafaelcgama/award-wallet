from fastapi.testclient import TestClient
from pydantic import SecretStr

from award_wallet import fetching
from award_wallet.models import LoyaltyAccount, SyncStatus
from award_wallet.web import create_app

from conftest import post_form


class FakeSites:
    """Stands in for Chrome: answers each fetch from a script."""

    def __init__(self):
        self.answers: dict[str, object] = {}
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, provider, credentials, state, *, with_person, screenshot_to=None):
        self.calls.append((provider.key, with_person))
        answer = self.answers.get(provider.key, 1000)
        if isinstance(answer, Exception):
            raise answer
        return fetching.Fetched(balance=answer, session_state={"cookies": [], "origins": [], "seen": state})


def open_app(settings, sites):
    desktop = settings.model_copy(update={"desktop_token": SecretStr("t"), "auto_fetch": True})
    app = create_app(desktop)
    app.state.refresher._fetch = sites
    return app


def link_with_login(window, provider):
    response = post_form(
        window,
        "/accounts/new",
        {"provider": provider, "credential_username": "me", "credential_password": "pw"},
        token_from=f"/accounts/new?provider={provider}",
    )
    assert response.status_code == 200
    return response


def test_saving_a_login_opens_the_sign_in_window_and_fetches(settings):
    sites = FakeSites()
    sites.answers["capital_one"] = 52300
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        page = link_with_login(window, "capital_one")
        assert "A Chrome window is opening to sign in to Capital One" in page.text
        app.state.refresher.wait()
        assert sites.calls == [("capital_one", True)]
        page = window.get("/").text
        assert "52,300" in page and "Up to date" in page and "Refresh now" in page


def test_every_launch_refreshes_quietly_and_remembers_the_browser(settings):
    sites = FakeSites()
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        link_with_login(window, "united")
        app.state.refresher.wait()

    sites.calls.clear()
    sites.answers["united"] = 2000
    relaunched = open_app(settings, sites)
    with TestClient(relaunched, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        relaunched.state.refresher.wait()
        window.get("/")  # a second visit in the same launch doesn't refresh again
        relaunched.state.refresher.wait()
        assert sites.calls == [("united", False)]
        assert "2,000" in window.get("/").text
        with relaunched.state.sessionmaker() as db:
            account = db.query(LoyaltyAccount).one()
            from award_wallet.services import accounts

            # The browser state saved last time was handed back, encrypted at rest.
            assert accounts.read_session_state(relaunched.state.vault, account)["seen"] is not None
            assert b"cookies" not in account.session_state_encrypted


def test_security_code_request_asks_for_you_and_is_not_retried(settings):
    sites = FakeSites()
    sites.answers["chase"] = fetching.NeedsPerson("Chase wants to confirm it's you. Click Sign in to enter the code.")
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        response = link_with_login(window, "chase")
        app.state.refresher.wait()
        account_page = window.get(response.url).text
        assert "Needs your sign-in" in account_page
        assert "Sign in to Chase" in account_page
        assert "Chase wants to confirm" in account_page

        sites.calls.clear()
        post_form(window, "/refresh", {}, token_from="/")
        app.state.refresher.wait()
        assert sites.calls == []  # not hammered in the background

        sites.answers["chase"] = 80000
        post_form(window, response.url.path + "/sign-in", {}, token_from=response.url.path)
        app.state.refresher.wait()
        assert sites.calls == [("chase", True)]
        assert "80,000" in window.get("/").text


def test_nothing_is_fetched_when_fetching_is_off(settings, client):
    client.app.state.refresher._fetch = FakeSites()
    link_with_login(client, "united")
    client.app.state.refresher.wait()
    assert client.app.state.refresher._fetch.calls == []
    assert "Refresh now" not in client.get("/").text


def test_failed_fetch_shows_why(settings):
    sites = FakeSites()
    sites.answers["united"] = RuntimeError("boom")
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        link_with_login(window, "united")
        app.state.refresher.wait()
        with app.state.sessionmaker() as db:
            assert db.query(LoyaltyAccount).one().sync_status == SyncStatus.ERROR
        assert "Couldn&#39;t reach United Airlines" in window.get("/").text


def test_connected_program_page_is_just_the_balance(settings):
    sites = FakeSites()
    sites.answers["capital_one"] = 221083
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        response = link_with_login(window, "capital_one")
        app.state.refresher.wait()
        page = window.get(response.url).text
        assert "221,083" in page
        assert "<summary>Change saved login</summary>" in page
        assert "<summary>Enter a balance by hand</summary>" in page
        assert "<h2>Capital One login</h2>" not in page


def test_programs_refresh_at_the_same_time(settings):
    import threading
    import time

    running, most = [], []
    lock = threading.Lock()

    def slow_site(provider, credentials, state, *, with_person, screenshot_to=None):
        with lock:
            running.append(provider.key)
            most.append(len(running))
        time.sleep(0.6)
        with lock:
            running.remove(provider.key)
        return fetching.Fetched(balance=1, session_state={"cookies": [], "origins": []})

    app = open_app(settings, slow_site)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        for provider in ("united", "chase", "capital_one"):
            link_with_login(window, provider)
        app.state.refresher.wait()
    assert max(most) >= 2
