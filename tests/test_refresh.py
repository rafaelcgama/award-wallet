import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from award_wallet import fetching
from award_wallet.models import BalanceSnapshot, LoyaltyAccount, SyncStatus
from award_wallet.services import accounts
from award_wallet.web import create_app

from conftest import CSRF_PATTERN, post_form

# Stands in for a picture of a site's page.
PICTURE = b"\xff\xd8\xff\xe0 a picture of the page \xff\xd9"


class FakeSites:
    """Stands in for Chrome: answers each fetch from a script. calls says, for each fetch, whether
    you were signing in (with the page shown in the window) or it was a refresh."""

    def __init__(self):
        self.answers: dict[str, object] = {}
        self.calls: list[tuple[str, bool]] = []
        self.profiles: list = []
        self.seeds: list = []
        self.typed: list[bool] = []
        self.logins: list[dict] = []

    def __call__(
        self,
        provider,
        credentials,
        profile,
        *,
        view=None,
        type_login=True,
        screenshot_to=None,
        seed_cookies=None,
        on_new_login=None,
    ):
        self.calls.append((provider.key, view is not None))
        self.profiles.append(profile)
        self.seeds.append(seed_cookies)
        self.typed.append(type_login)
        self.logins.append(credentials)
        answer = self.answers.get(provider.key, 1000)
        if callable(answer):
            answer = answer(view) if answer.__code__.co_argcount == 1 else answer(view, on_new_login)
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


def test_saving_a_login_fetches_out_of_sight(settings):
    sites = FakeSites()
    sites.answers["capital_one"] = 52300
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        page = link_with_login(window, "capital_one")
        assert "Chrome window" not in page.text
        app.state.refresher.wait()
        assert sites.calls == [("capital_one", False)]  # no window
        page = window.get("/").text
        assert "52,300" in page and "Up to date" in page and "Refresh now" in page


def until(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    return condition()


def test_sign_in_shows_the_site_in_the_window(settings):
    sites = FakeSites()
    sites.answers["capital_one"] = fetching.NeedsPerson("Capital One wants to confirm it's you. Click Sign in.")
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        path = link_with_login(window, "capital_one").url.path
        app.state.refresher.wait()
        dashboard = window.get("/").text
        assert "Needs your sign-in" in dashboard and "Click Sign in" in dashboard
        assert sites.calls == [("capital_one", False)]  # a refresh shows nothing

        note = "Capital One wants to confirm it's you. Do what it asks below."
        shown, you_finished = threading.Event(), threading.Event()

        def capital_one_asks(view):
            view.show(PICTURE, 1200, 800)
            view.say(note)
            shown.set()
            you_finished.wait(10)
            return 52300

        sites.answers["capital_one"] = capital_one_asks
        page = post_form(window, path + "/sign-in", {"back": "dashboard"}, token_from="/")
        assert page.url.path == path + "/sign-in" and page.url.query == b"back=dashboard"
        assert ">Sign in to Capital One</h1>" in page.text and 'href="/">← All programs' in page.text
        assert shown.wait(10)

        status = window.get(path + "/sign-in/status?after=0").json()
        assert status["state"] == "open" and status["note"] == note
        assert (status["picture"], status["width"], status["height"]) == (1, 1200, 800)
        picture = window.get(path + f"/sign-in/picture?n={status['picture']}")
        assert picture.content == PICTURE and picture.headers["content-type"] == "image/jpeg"
        assert picture.headers["cache-control"] == "no-store"  # never kept on disk
        for elsewhere in (window.get("/").text, window.get(path).text):
            assert "Waiting for you" in elsewhere and "Continue signing in" in elsewhere

        you_finished.set()
        app.state.refresher.wait()
        assert sites.calls == [("capital_one", False), ("capital_one", True)]
        assert window.get(path + "/sign-in/status?after=0").json() == {"state": "gone"}
        assert window.get(path + "/sign-in", follow_redirects=False).headers["location"] == path
        assert window.get(path + "/sign-in/picture").status_code == 404
        dashboard = window.get("/").text
        assert "52,300" in dashboard and "Up to date" in dashboard and "Waiting for you" not in dashboard


def test_the_status_waits_for_something_new(settings):
    sites = FakeSites()
    shown, next_picture = threading.Event(), threading.Event()

    def chase(view):
        view.show(PICTURE, 1200, 800)
        shown.set()
        next_picture.wait(10)
        view.show(PICTURE, 1200, 800)
        time.sleep(0.2)
        return 80000

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = fetching.NeedsPerson("Chase wants to confirm it's you. Click Sign in.")
        path = link_with_login(window, "chase").url.path
        app.state.refresher.wait()
        sites.answers["chase"] = chase
        post_form(window, path + "/sign-in", {}, token_from=path)
        assert shown.wait(10)
        version = window.get(path + "/sign-in/status").json()["version"]
        threading.Timer(0.3, next_picture.set).start()
        started = time.monotonic()
        status = window.get(path + f"/sign-in/status?after={version}").json()
        assert time.monotonic() - started >= 0.25  # it waited for the next picture
        assert status["picture"] == 2 and status["version"] > version
        app.state.refresher.wait()


def test_your_clicks_and_keys_reach_the_page(settings):
    sites = FakeSites()
    shown, received = threading.Event(), []

    def you_type_the_code(view):
        view.show(PICTURE, 1200, 800)
        shown.set()
        until(lambda: received.extend(view.take()) or len(received) >= 3)
        return 80000

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = fetching.NeedsPerson("Chase wants to confirm it's you. Click Sign in.")
        path = link_with_login(window, "chase").url.path
        app.state.refresher.wait()
        sites.answers["chase"] = you_type_the_code
        sign_in_page = post_form(window, path + "/sign-in", {}, token_from=path).text
        token = CSRF_PATTERN.search(sign_in_page).group(1)
        assert f'data-token="{token}"' in sign_in_page
        assert shown.wait(10)

        def send(events, *, csrf=token, **request):
            data = {"csrf_token": csrf, "events": events if isinstance(events, str) else json.dumps(events)}
            return window.post(path + "/sign-in/input", data=data, **request).status_code

        # Anything but a click on the page, a scroll, some text or a known key is turned away.
        for bad in (
            [{"kind": "click", "x": 1300, "y": 10}],
            [{"kind": "click", "x": True, "y": 10}],
            [{"kind": "scroll", "x": 1, "y": 1, "dx": 0, "dy": 99999}],
            [{"kind": "text", "text": "line one\nline two"}],
            [{"kind": "text", "text": ""}],
            [{"kind": "key", "key": "F12"}],
            [{"kind": "script", "source": "alert(1)"}],
            [{"kind": "click", "x": 1, "y": 1}] * 51,
            [],
            "not json",
            "x" * 20_001,
        ):
            assert send(bad) == 400, bad
        assert send([{"kind": "click", "x": 1, "y": 1}], csrf="wrong") == 403
        assert send([{"kind": "click", "x": 1, "y": 1}], headers={"Origin": "https://evil.example"}) == 403

        assert send([{"kind": "click", "x": 600, "y": 400.5}]) == 204
        assert send([{"kind": "text", "text": "123 456 é"}, {"kind": "key", "key": "Enter", "shift": "yes"}]) == 204
        app.state.refresher.wait()
        assert received == [
            {"kind": "click", "x": 600.0, "y": 400.5},
            {"kind": "text", "text": "123 456 é"},
            {"kind": "key", "key": "Enter", "shift": False},
        ]
        assert send([{"kind": "click", "x": 1, "y": 1}]) == 409  # the sign-in is over


def test_only_the_apps_own_window_sees_a_sign_in(settings):
    sites = FakeSites()
    shown, you_finished = threading.Event(), threading.Event()

    def chase(view):
        view.show(PICTURE, 1200, 800)
        shown.set()
        you_finished.wait(10)
        return 80000

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = fetching.NeedsPerson("Chase wants to confirm it's you. Click Sign in.")
        path = link_with_login(window, "chase").url.path
        app.state.refresher.wait()
        sites.answers["chase"] = chase
        post_form(window, path + "/sign-in", {}, token_from=path)
        assert shown.wait(10)
        # Another web page in a browser on this Mac can't load the picture or the status.
        for address in ("/sign-in/picture", "/sign-in/status"):
            assert window.get(path + address, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        # Nor can anything that didn't open the app's window.
        with TestClient(app, base_url="http://127.0.0.1") as stranger:
            assert stranger.get(path + "/sign-in/picture").status_code == 403
            assert PICTURE not in stranger.get(path + "/sign-in/picture").content
        you_finished.set()
        app.state.refresher.wait()


def test_stopping_a_sign_in(settings):
    sites = FakeSites()
    shown = threading.Event()

    def chase(view):
        view.show(PICTURE, 1200, 800)
        shown.set()
        assert until(lambda: view.stopped)
        raise fetching.NeedsPerson("You stopped the sign-in to Chase. Click Sign in to try again.")

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = fetching.NeedsPerson("Chase wants to confirm it's you. Click Sign in.")
        path = link_with_login(window, "chase").url.path
        app.state.refresher.wait()
        sites.answers["chase"] = chase
        post_form(window, path + "/sign-in", {"back": "dashboard"}, token_from=path)
        assert shown.wait(10)
        page = post_form(window, path + "/sign-in/stop", {"back": "dashboard"}, token_from=path + "/sign-in")
        assert page.url.path == "/"
        assert window.get(path + "/sign-in/status").json() == {"state": "gone"}
        app.state.refresher.wait()
        account_page = window.get(path).text
        assert "You stopped the sign-in to Chase" in account_page and "Needs your sign-in" in account_page


def test_a_sign_in_you_dont_finish_keeps_a_turned_down_login_from_refreshes(settings):
    sites = FakeSites()
    sites.answers["chase"] = fetching.LoginRejected("Chase didn't take the saved login.")
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        path = link_with_login(window, "chase").url.path
        app.state.refresher.wait()
        sites.answers["chase"] = fetching.NeedsPerson("The sign-in to Chase timed out before it finished.")
        post_form(window, path + "/sign-in", {}, token_from=path)
        app.state.refresher.wait()
        with app.state.sessionmaker() as db:
            assert db.query(LoyaltyAccount).one().sync_status == SyncStatus.LOGIN_REJECTED
        sites.calls.clear()
        post_form(window, "/refresh", {}, token_from="/")
        app.state.refresher.wait()
        assert sites.calls == []  # the turned-down password isn't tried again


def test_sign_in_waits_for_a_refresh_already_running(settings):
    sites = FakeSites()
    running, let_go = threading.Event(), threading.Event()

    def slow_refresh(view):
        running.set()
        let_go.wait(10)
        return 80000

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = slow_refresh
        path = link_with_login(window, "chase").url.path
        assert running.wait(10)
        page = post_form(window, path + "/sign-in", {}, token_from=path)
        assert page.url.path == path and "Chase is refreshing right now" in page.text
        let_go.set()
        app.state.refresher.wait()
        assert sites.calls == [("chase", False)]


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


def test_the_app_says_what_a_site_wants_while_you_sign_in(settings):
    sites = FakeSites()
    window_up, you_finished = threading.Event(), threading.Event()

    def chase_asks(view):
        view.say("Chase wants to confirm it's you, usually only the first time.")
        window_up.set()
        you_finished.wait(10)
        return 80000

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = fetching.NeedsPerson("Chase wants to confirm it's you. Click Sign in.")
        response = link_with_login(window, "chase")
        app.state.refresher.wait()
        sites.answers["chase"] = chase_asks
        post_form(window, response.url.path + "/sign-in", {}, token_from=response.url.path)
        assert window_up.wait(10)
        for page in (window.get("/").text, window.get(response.url).text):
            assert "Waiting for you" in page and "Continue signing in" in page
        sign_in_page = window.get(response.url.path + "/sign-in").text
        assert "Chase wants to confirm it&#39;s you, usually only the first time." in sign_in_page
        you_finished.set()
        app.state.refresher.wait()
        page = window.get("/").text
        assert "80,000" in page and "Waiting for you" not in page and "confirm it&#39;s you" not in page


def test_a_rejected_login_is_not_retried_until_saved_again(settings):
    sites = FakeSites()
    sites.answers["chase"] = fetching.LoginRejected(
        "Chase didn't take the saved login. Click Sign in to sign in once; Award Wallet keeps the login that works."
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
        assert "Skipped Ultimate Rewards: the site didn&#39;t take the saved login" in page.text

        sites.answers["chase"] = 80000
        post_form(
            window,
            response.url.path + "/login",
            {"credential_username": "me", "credential_password": "right"},
            token_from=response.url.path,
        )
        app.state.refresher.wait()
        assert sites.calls == [("chase", False)]
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

    def slow_site(provider, credentials, profile, **options):
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


def test_signing_in_after_a_turned_down_login_keeps_the_one_that_works(settings):
    sites = FakeSites()
    sites.answers["chase"] = fetching.LoginRejected("Chase didn't take the saved login.")
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        response = link_with_login(window, "chase")
        app.state.refresher.wait()
        dashboard = window.get("/").text
        assert "Chase didn&#39;t take the saved login." in dashboard
        assert f'action="/accounts/{response.url.path.rsplit("/", 1)[-1]}/sign-in"' in dashboard

        def you_sign_in(view, on_new_login):
            on_new_login({"password": "the right one"})
            return 80000

        sites.answers["chase"] = you_sign_in
        sites.typed.clear()
        page = post_form(
            window, response.url.path + "/sign-in", {"back": "dashboard"}, token_from="/", follow_redirects=False
        )
        assert page.headers["location"] == response.url.path + "/sign-in?back=dashboard"
        app.state.refresher.wait()
        assert sites.typed == [False]  # you sign in; the app doesn't try the old login again
        with app.state.sessionmaker() as db:
            account = db.query(LoyaltyAccount).one()
            assert accounts.read_credentials(app.state.vault, account) == {
                "username": "me",
                "password": "the right one",
            }
            assert account.sync_status == SyncStatus.OK
        assert app.state.refresher.browser_profile(account.id) == sites.profiles[-1]

        sites.answers["chase"] = 80000
        post_form(window, "/refresh", {}, token_from="/")
        app.state.refresher.wait()
        assert sites.logins[-1] == {"username": "me", "password": "the right one"}
        assert sites.typed[-1] is True


def test_the_same_balance_again_adds_no_history(settings):
    sites = FakeSites()
    sites.answers["united"] = 52300
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        response = link_with_login(window, "united")
        app.state.refresher.wait()
        for _ in range(3):
            post_form(window, "/refresh", {}, token_from="/")
            app.state.refresher.wait()
        with app.state.sessionmaker() as db:
            assert db.query(BalanceSnapshot).count() == 1
        assert window.get(response.url).text.count('<td class="num">52,300</td>') == 1
        assert "Updated just now" in window.get("/").text


def test_a_browser_profile_stays_inside_the_browser_folder(app):
    for not_an_id in ("", ".", "..", "../Diagnostics", "a/b"):
        with pytest.raises(ValueError):
            app.state.refresher.browser_profile(not_an_id)


def test_a_balance_that_falls_by_more_than_half_waits_for_you(settings):
    # A fall that big could be some other number on the site's page, or points you didn't spend.
    sites = FakeSites()
    sites.answers["united"] = 80000
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        page = link_with_login(window, "united").url.path
        app.state.refresher.wait()

        def refresh(balance):
            sites.answers["united"] = balance
            post_form(window, "/refresh", {}, token_from="/")
            app.state.refresher.wait()

        def state():
            with app.state.sessionmaker() as db:
                account = db.query(LoyaltyAccount).one()
                newest = max(account.snapshots, key=lambda snapshot: snapshot.captured_at)
                return account.sync_status, account.held_balance, newest.balance

        refresh(20000)
        assert state() == (SyncStatus.CHECK_BALANCE, 20000, 80000)
        assert "The last refresh read 20,000. Is that right?" in window.get("/").text
        shown = window.get(page).text
        assert "The last refresh read 20,000 miles, down from 80,000" in shown
        assert ">Refresh</button>" in shown  # signing in went fine, so no Sign in button
        refresh(80000)  # the old balance again: the 20,000 was a misreading
        assert state() == (SyncStatus.OK, None, 80000)

        refresh(20000)
        post_form(window, f"{page}/held", {"keep": "old"}, token_from=page)
        assert state() == (SyncStatus.OK, None, 80000)
        refresh(20000)
        post_form(window, f"{page}/held", {"keep": "new"}, token_from=page)
        assert state() == (SyncStatus.OK, None, 20000)
        refresh(12000)  # down, but not by more than half
        assert state() == (SyncStatus.OK, None, 12000)

        refresh(1000)
        post_form(window, f"{page}/balance", {"balance": "11,500"}, token_from=page)  # entered by hand
        assert state() == (SyncStatus.OK, None, 11500)


def test_removing_a_program_while_it_refreshes(settings, caplog):
    sites = FakeSites()
    running, let_go = threading.Event(), threading.Event()

    def chase(view):
        sites.profiles[-1].mkdir(parents=True)  # Chrome writes its profile while it runs
        running.set()
        let_go.wait(10)
        return 80000

    sites.answers["chase"] = chase
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        path = link_with_login(window, "chase").url.path
        assert running.wait(10)
        profile = sites.profiles[-1]
        post_form(window, path + "/delete", {}, token_from=path)
        assert profile.exists()  # still Chrome's while it runs
        let_go.set()
        app.state.refresher.wait(10)
        assert not profile.exists()
        with app.state.sessionmaker() as db:
            assert db.query(LoyaltyAccount).count() == db.query(BalanceSnapshot).count() == 0
    assert not [record for record in caplog.records if record.levelname == "ERROR"]


def test_removing_a_program_stops_its_sign_in(settings):
    sites = FakeSites()
    shown, stopped = threading.Event(), threading.Event()

    def chase(view):
        sites.profiles[-1].mkdir(parents=True, exist_ok=True)
        view.show(PICTURE, 1200, 800)
        shown.set()
        if until(lambda: view.stopped):
            stopped.set()
        raise fetching.NeedsPerson("You stopped the sign-in to Chase. Click Sign in to try again.")

    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["chase"] = fetching.NeedsPerson("Chase wants to confirm it's you. Click Sign in.")
        path = link_with_login(window, "chase").url.path
        app.state.refresher.wait(10)
        sites.answers["chase"] = chase
        post_form(window, path + "/sign-in", {}, token_from=path)
        assert shown.wait(10)
        post_form(window, path + "/delete", {}, token_from=path)
        app.state.refresher.wait(10)
        assert stopped.is_set()
        assert not sites.profiles[-1].exists()


def test_a_login_saved_during_a_refresh_wins(settings):
    # The refresh that was running belongs to the old login: what it found is dropped, and the
    # new login is fetched right after, in a new Chrome profile since the username changed.
    sites = FakeSites()
    running, let_go = threading.Event(), threading.Event()
    profile_was_there = []

    def chase(view, on_new_login):
        profile = sites.profiles[-1]
        profile_was_there.append(profile.exists())
        if len(sites.calls) > 1:
            return 222
        profile.mkdir(parents=True)
        running.set()
        let_go.wait(10)
        on_new_login({"username": "me", "password": "learned"})
        return 111

    sites.answers["chase"] = chase
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        path = link_with_login(window, "chase").url.path
        assert running.wait(10)
        new_login = {"credential_username": "someone-else", "credential_password": "new"}
        post_form(window, path + "/login", new_login, token_from=path)
        let_go.set()
        app.state.refresher.wait(10)
        assert [login["username"] for login in sites.logins] == ["me", "someone-else"]
        assert profile_was_there == [False, False]
        with app.state.sessionmaker() as db:
            account = db.query(LoyaltyAccount).one()
            assert accounts.read_credentials(app.state.vault, account) == {
                "username": "someone-else",
                "password": "new",
            }
            assert [snapshot.balance for snapshot in account.snapshots] == [222]


def test_chrome_profiles_no_program_owns_are_deleted_when_the_app_opens(settings):
    sites = FakeSites()
    with TestClient(open_app(settings, sites), base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        link_with_login(window, "chase")
        window.app.state.refresher.wait(10)
    kept = sites.profiles[-1]
    kept.mkdir(parents=True, exist_ok=True)
    left_behind = kept.parent / "0b5c7a52-2d0e-4c1a-9a51-6b8f4f5e2c11"
    left_behind.mkdir()
    not_a_profile = kept.parent / "Notes"
    not_a_profile.mkdir()

    with TestClient(open_app(settings, sites), base_url="http://127.0.0.1") as window:
        window.get("/?token=t")  # the next launch
        window.app.state.refresher.wait(10)
    assert kept.exists() and not_a_profile.exists()
    assert not left_behind.exists()


def test_waiting_for_refreshes_gives_up_at_its_time_limit(settings):
    sites = FakeSites()
    let_go = threading.Event()
    sites.answers["chase"] = lambda view: let_go.wait(10) and 1000
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        link_with_login(window, "chase")
        with pytest.raises(TimeoutError):
            app.state.refresher.wait(0.2)
        let_go.set()
        app.state.refresher.wait(10)


def _three_slow_refreshes(window, sites, let_go):
    """Links three programs whose refreshes hold every refresh slot until let_go is set."""
    for provider in ("united", "chase", "capital_one"):
        sites.answers[provider] = lambda view: let_go.wait(10) and 1000
        link_with_login(window, provider)
    assert until(lambda: len(sites.calls) >= 3)


def test_a_sign_in_starts_without_waiting_for_refreshes(settings):
    sites = FakeSites()
    let_go = threading.Event()
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        sites.answers["delta"] = fetching.NeedsPerson("Delta wants to confirm it's you. Click Sign in.")
        path = link_with_login(window, "delta").url.path
        app.state.refresher.wait(10)
        _three_slow_refreshes(window, sites, let_go)
        sites.answers["american"] = 1000
        link_with_login(window, "american")  # waits its turn behind the three

        sites.answers["delta"] = 5000
        post_form(window, path + "/sign-in", {}, token_from=path)
        assert until(lambda: ("delta", True) in sites.calls)
        assert ("american", False) not in sites.calls
        let_go.set()
        app.state.refresher.wait(10)
        assert sites.calls[-1] == ("american", False)


def test_a_sign_in_takes_the_place_of_a_refresh_waiting_its_turn(settings):
    sites = FakeSites()
    let_go = threading.Event()
    app = open_app(settings, sites)
    with TestClient(app, base_url="http://127.0.0.1") as window:
        window.get("/?token=t")
        _three_slow_refreshes(window, sites, let_go)
        sites.answers["delta"] = 5000
        path = link_with_login(window, "delta").url.path  # its refresh waits its turn
        page = post_form(window, path + "/sign-in", {}, token_from=path)
        assert "refreshing right now" not in page.text
        assert until(lambda: ("delta", True) in sites.calls)
        let_go.set()
        app.state.refresher.wait(10)
        assert [call for call in sites.calls if call[0] == "delta"] == [("delta", True)]
