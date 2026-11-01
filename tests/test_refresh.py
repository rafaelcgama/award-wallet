import threading

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
        self.profiles: list = []
        self.seeds: list = []

    def __call__(
        self, provider, credentials, profile, *, with_person, screenshot_to=None, seed_cookies=None, on_needs_you=None
    ):
        self.calls.append((provider.key, with_person))
        self.profiles.append(profile)
        self.seeds.append(seed_cookies)
        answer = self.answers.get(provider.key, 1000)
        if callable(answer):
            answer = answer(on_needs_you)
        if isinstance(answer, Exception):
            raise answer
        return answer


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


def test_every_launch_refreshes_quietly_with_the_same_browser(settings):
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
    # Both launches used the program's own Chrome profile in the app's folder, which is what
    # lets the site remember this Mac.
    with relaunched.state.sessionmaker() as db:
        account = db.query(LoyaltyAccount).one()
    assert sites.profiles == [settings.browser_dir / account.id] * 2


def test_cookies_from_older_versions_are_carried_over_once(settings):
    from award_wallet.services import accounts

    sites = FakeSites()
    app = open_app(settings, sites)
    cookies = [{"name": "device", "value": "known", "domain": ".united.com", "path": "/"}]
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["united"] = fetching.NeedsPerson("United wants to confirm it's you.")
        link_with_login(window, "united")
        app.state.refresher.wait()
        with app.state.sessionmaker() as db:
            account = db.query(LoyaltyAccount).one()
            accounts.save_session_state(app.state.vault, account, {"cookies": cookies, "origins": []})
            db.commit()

        sites.seeds.clear()
        post_form(window, "/refresh", {}, token_from="/")
        app.state.refresher.wait()
        post_form(window, "/refresh", {}, token_from="/")
        app.state.refresher.wait()
        assert sites.seeds == [cookies, None]
        with app.state.sessionmaker() as db:
            assert db.query(LoyaltyAccount).one().session_state_encrypted is None


def test_an_unanswered_security_code_is_asked_again_on_the_next_refresh(settings):
    sites = FakeSites()
    sites.answers["chase"] = fetching.NeedsPerson("The Chase window timed out before the sign-in finished. Try again.")
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        response = link_with_login(window, "chase")
        app.state.refresher.wait()
        account_page = window.get(response.url).text
        assert "Needs your sign-in" in account_page
        assert "Sign in to Chase" in account_page
        assert "The Chase window timed out" in account_page

        sites.calls.clear()
        sites.answers["chase"] = 80000
        post_form(window, "/refresh", {}, token_from="/")
        app.state.refresher.wait()
        assert sites.calls == [("chase", False)]
        assert "80,000" in window.get("/").text


def test_the_app_says_what_a_site_wants_while_its_window_is_up(settings):
    sites = FakeSites()
    window_up, you_finished = threading.Event(), threading.Event()

    def chase_asks(on_needs_you):
        on_needs_you("Chase wants to confirm it's you, usually only the first time.")
        window_up.set()
        you_finished.wait(10)
        return 80000

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = chase_asks
        response = link_with_login(window, "chase")
        assert window_up.wait(10)
        for page in (window.get("/").text, window.get(response.url).text):
            assert "Waiting for you" in page
            assert "Chase wants to confirm it&#39;s you, usually only the first time." in page
        you_finished.set()
        app.state.refresher.wait()
        page = window.get("/").text
        assert "80,000" in page and "Waiting for you" not in page and "confirm it&#39;s you" not in page


def test_a_rejected_login_is_not_retried_until_saved_again(settings):
    sites = FakeSites()
    sites.answers["chase"] = fetching.LoginRejected(
        "Chase didn't accept the saved username or password. Save it again."
    )
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        response = link_with_login(window, "chase")
        app.state.refresher.wait()
        account_page = window.get(response.url).text
        assert "Check your login" in account_page
        assert '<details class="manual" open>\n    <summary>Change saved login</summary>' in account_page

        sites.calls.clear()
        page = post_form(window, "/refresh", {}, token_from="/")
        app.state.refresher.wait()
        assert sites.calls == []  # retrying a wrong password could lock the account
        assert "Skipped Ultimate Rewards: the site didn&#39;t accept the saved login" in page.text

        sites.answers["chase"] = 80000
        post_form(
            window,
            response.url.path + "/login",
            {"credential_username": "me", "credential_password": "right"},
            token_from=response.url.path,
        )
        app.state.refresher.wait()
        assert sites.calls == [("chase", True)]
        assert "80,000" in window.get("/").text


def test_the_browser_is_forgotten_with_its_login(settings):
    sites = FakeSites()
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        path = link_with_login(window, "chase").url.path
        app.state.refresher.wait()
        profile = sites.profiles[-1]

        def save_login(username):
            profile.mkdir(parents=True, exist_ok=True)
            post_form(
                window,
                path + "/login",
                {"credential_username": username, "credential_password": "new"},
                token_from=path,
            )
            app.state.refresher.wait()

        save_login("me")  # a new password: the site still knows this Mac
        assert profile.exists()
        save_login("someone-else")  # another login starts fresh
        assert not profile.exists()

        profile.mkdir(parents=True)
        post_form(window, path + "/delete", {}, token_from=path)
        assert not profile.exists()


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

    def slow_site(
        provider, credentials, profile, *, with_person, screenshot_to=None, seed_cookies=None, on_needs_you=None
    ):
        with lock:
            running.append(provider.key)
            most.append(len(running))
        time.sleep(0.6)
        with lock:
            running.remove(provider.key)
        return 1

    app = open_app(settings, slow_site)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        for provider in ("united", "chase", "capital_one"):
            link_with_login(window, provider)
        app.state.refresher.wait()
    assert max(most) >= 2
