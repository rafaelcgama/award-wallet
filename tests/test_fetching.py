import glob
import os

import pytest
from fakebank import CODE, PASSWORD, USERNAME, FakeBank, serve

from award_wallet import fetching
from award_wallet.providers import Provider

CHROME = next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")), None)
needs_browser = pytest.mark.skipif(CHROME is None and "AW_BROWSER_PATH" not in os.environ, reason="no browser")


@pytest.fixture(autouse=True)
def browser_path(monkeypatch):
    if CHROME and "AW_BROWSER_PATH" not in os.environ:
        monkeypatch.setenv("AW_BROWSER_PATH", CHROME)
    monkeypatch.setattr(fetching, "CHALLENGE_GRACE", 4)
    monkeypatch.setattr(fetching, "QUIET_TIMEOUT", 20)


@pytest.fixture
def site():
    servers = []

    def make(**options):
        bank = FakeBank(**options)
        server, thread, url = serve(bank)
        servers.append(server)

        class Site(Provider):
            key = name = program = "fake"
            unit = "miles"
            balance_url = f"{url}/account"
            balance_patterns = (r"(\d[\d,]*)\s*miles\b",)

        return bank, Site()

    yield make
    for server in servers:
        server.should_exit = True


LOGIN = {"username": USERNAME, "password": PASSWORD}


def fetch(site, profile, **options):
    return fetching.fetch_balance(site, LOGIN, profile, headless=True, **options)


def type_code(page):
    box = page.locator("input[name=code]")
    if box.count() and box.is_visible() and not box.input_value():
        box.fill(CODE)
        box.press("Enter")


@needs_browser
@pytest.mark.parametrize("options", [{}, {"two_step": True}, {"in_iframe": True}])
def test_after_one_security_code_refreshes_need_nothing(site, tmp_path, options):
    bank, provider = site(**options)
    profile = tmp_path / "profile"

    # A refresh that's not allowed to ask stops at the site's code request.
    with pytest.raises(fetching.NeedsPerson):
        fetch(provider, profile, may_ask=False)

    # Normally the window comes up for the code (here, type_code plays the person).
    assert fetch(provider, profile, while_waiting=type_code) == 52300
    assert bank.codes_asked == 2

    # Later refreshes use the same Chrome profile, so the site knows this browser: no code, even
    # after the site's session ends and the login has to be typed again.
    bank.expire_sessions()
    bank.balance = 61000
    assert fetch(provider, profile, may_ask=False) == 61000
    assert bank.codes_asked == 2


@needs_browser
def test_cookies_kept_by_older_versions_carry_over(site, tmp_path):
    bank, provider = site()
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", may_ask=False, seed_cookies=cookies) == 52300
    assert bank.codes_asked == 0


@needs_browser
def test_a_balance_counts_once_it_stops_changing(site, tmp_path):
    bank, provider = site(shows="counting", balance=163918)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", may_ask=False, seed_cookies=cookies) == 163918


@needs_browser
def test_scrolls_to_a_balance_that_loads_when_seen(site, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "SCROLL_EVERY", 0.5)
    bank, provider = site(shows="below")
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", may_ask=False, seed_cookies=cookies) == 52300


@needs_browser
def test_the_sites_own_error_is_passed_on(site, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "TROUBLE_GRACE", 1)
    bank, provider = site(shows="trouble")
    with pytest.raises(fetching.FetchProblem, match="fake says: “We can’t access your account information right now"):
        fetch(provider, tmp_path / "profile", while_waiting=type_code)


@needs_browser
def test_a_page_without_the_balance_gives_up_with_a_screenshot(site, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "READ_TIMEOUT", 2)
    bank, provider = site(shows="empty")
    with pytest.raises(fetching.FetchProblem, match="Signed in to fake, but couldn't find your miles"):
        fetch(provider, tmp_path / "profile", while_waiting=type_code, screenshot_to=tmp_path / "shot.png")
    assert (tmp_path / "shot.png").exists()


@needs_browser
def test_the_log_shows_each_step_but_never_the_login(site, tmp_path, caplog):
    bank, provider = site()
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        with pytest.raises(fetching.NeedsPerson):
            fetch(provider, tmp_path / "profile", may_ask=False)
    assert "submitted the login" in caplog.text
    assert "/verify" in caplog.text
    assert PASSWORD not in caplog.text and USERNAME not in caplog.text


@needs_browser
def test_wrong_password_is_reported(site, tmp_path):
    bank, provider = site()
    with pytest.raises(fetching.LoginRejected):
        fetching.fetch_balance(
            provider,
            {"username": USERNAME, "password": "nope"},
            tmp_path / "profile",
            headless=True,
            screenshot_to=tmp_path / "shot.png",
        )
    assert (tmp_path / "shot.png").exists()


def test_find_balance_reads_the_first_match():
    assert fetching.find_balance("Earn 2X miles\nRewards\n52,300 Miles", (r"(\d[\d,]*)\s*miles\b",)) == 52300
    assert fetching.find_balance("nothing here", (r"(\d[\d,]*)\s*miles\b",)) is None


def test_a_sites_numbered_servers_count_as_the_same_site():
    dashboard = "https://secure.chase.com/web/auth/dashboard"
    assert fetching._same_site("https://secure07c.chase.com/web/auth/dashboard#/dashboard/overview", dashboard)
    assert fetching._at_balance_page("https://secure07c.chase.com/web/auth/dashboard#/dashboard/overview", dashboard)
    assert not fetching._at_balance_page("https://secure.chase.com/web/auth/#/logon/logon/chaseOnline", dashboard)
    assert not fetching._same_site("https://www.chase.com.example.net/", dashboard)
    assert not fetching._same_site("about:blank", dashboard)
