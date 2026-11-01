import glob
import json
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
    """You, at the window: ask for the code by text if the site lets you choose, then type it."""
    text = page.get_by_role("button", name="Get a text")
    if text.count() and text.is_visible():
        text.click()
    box = page.locator("input[name=code]")
    if box.count() and box.is_visible() and not box.input_value():
        box.fill(CODE)
        box.press("Enter")


@needs_browser
@pytest.mark.parametrize(
    "options",
    [
        {},
        {"two_step": True},
        {"in_iframe": True},
        {"sign_in_on_page": True},
        {"confirm_in_place": True},
        {"clears_form_once": True},
    ],
)
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
    assert bank.searches == []  # the search box never got the username


@needs_browser
def test_a_username_box_on_the_account_page_is_filled(site, tmp_path, caplog):
    # United shows "Email or MileagePlus number" right on its account page, with a Continue button.
    bank, provider = site(sign_in_on_page=True)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        assert fetch(provider, tmp_path / "profile", may_ask=False, seed_cookies=cookies) == 52300
    assert "submitted the username" in caplog.text and "clicked the form's button" in caplog.text
    assert bank.searches == []


@needs_browser
def test_an_email_box_that_isnt_the_login_is_left_alone(site, tmp_path, monkeypatch):
    # The balance takes a while to show, and the page has a newsletter's email box meanwhile.
    monkeypatch.setattr(fetching, "SCROLL_EVERY", 0.5)
    bank, provider = site(shows="below", newsletter=True)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", may_ask=False, seed_cookies=cookies) == 52300
    assert bank.subscribed == [] and bank.searches == []


@needs_browser
def test_confirming_its_you_brings_the_window_up_with_a_note(site, tmp_path, caplog, monkeypatch):
    # Chase asks on its dashboard's own address, where the run otherwise keeps looking for the
    # number: the window comes up right away instead, and the app says what to do.
    monkeypatch.setattr(fetching, "CHALLENGE_GRACE", 60)
    bank, provider = site(confirm_in_place=True)
    notes = []
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        balance = fetch(
            provider,
            tmp_path / "profile",
            while_waiting=type_code,
            on_needs_you=notes.append,
            screenshot_to=tmp_path / "fake.png",
        )
    assert balance == 52300
    assert notes == [
        "fake wants to confirm it's you, usually only the first time. Finish it in the fake window; "
        "after that, refreshes run on their own."
    ]
    assert "the site asks to confirm it's you" in caplog.text
    assert (tmp_path / "fake-needs-you.png").exists()


@needs_browser
def test_a_login_the_site_cleared_is_typed_once_more(site, tmp_path, caplog):
    bank, provider = site(clears_form_once=True)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        assert fetch(provider, tmp_path / "profile", may_ask=False, seed_cookies=cookies) == 52300
    assert bank.logins == 2
    assert "the site cleared the login" in caplog.text


@needs_browser
def test_a_form_that_comes_back_with_a_message_is_left_to_you(site, tmp_path):
    # Whatever the site said, the app doesn't know it: it never types the password again over it.
    bank, provider = site(clears_form_once=True, says_once="Something about your sign-in needs attention.")
    with pytest.raises(fetching.NeedsPerson):
        fetch(provider, tmp_path / "profile", may_ask=False)
    assert bank.logins == 1


@needs_browser
def test_a_wrong_password_is_typed_only_once(site, tmp_path):
    bank, provider = site(clears_form_once=True)
    with pytest.raises(fetching.LoginRejected):
        fetching.fetch_balance(provider, {"username": USERNAME, "password": "nope"}, tmp_path / "p", headless=True)
    assert bank.logins == 2  # the one the site cleared, and one that it said was wrong


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
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    with pytest.raises(fetching.FetchProblem, match="Couldn't find your miles on fake's page"):
        fetch(provider, tmp_path / "profile", seed_cookies=cookies, screenshot_to=tmp_path / "shot.png")
    assert (tmp_path / "shot.png").exists()


@needs_browser
def test_a_window_thats_up_for_you_waits_for_you(site, tmp_path, monkeypatch):
    # You might be signing in on that very page: only your own time limit closes the window.
    monkeypatch.setattr(fetching, "READ_TIMEOUT", 1)
    monkeypatch.setattr(fetching, "PERSON_TIMEOUT", 4)
    bank, provider = site(shows="empty")
    with pytest.raises(fetching.NeedsPerson, match="timed out"):
        fetch(provider, tmp_path / "profile", with_person=True, while_waiting=type_code)


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


def test_chromes_own_prompts_are_turned_off(tmp_path):
    preferences = tmp_path / "Default" / "Preferences"
    fetching.quiet_profile(tmp_path)
    settings = json.loads(preferences.read_text())
    assert settings["credentials_enable_service"] is False
    assert settings["profile"] == {"password_manager_enabled": False, "exit_type": "Normal", "exited_cleanly": True}

    # Chrome's own settings are kept, and a run that was cut short doesn't ask to restore pages.
    settings["profile"].update(exit_type="Crashed", name="Person 1")
    settings["intl"] = {"selected_languages": "en-US"}
    preferences.write_text(json.dumps(settings))
    fetching.quiet_profile(tmp_path)
    settings = json.loads(preferences.read_text())
    assert settings["profile"]["exit_type"] == "Normal" and settings["profile"]["name"] == "Person 1"
    assert settings["intl"] == {"selected_languages": "en-US"}

    preferences.write_text("not json")
    fetching.quiet_profile(tmp_path)
    assert preferences.read_text() == "not json"


@pytest.mark.parametrize(
    ("field", "rank"),
    [
        ({"type": "text", "autocomplete": "username", "about": "userid username"}, 0),
        ({"type": "email", "autocomplete": "", "about": "email"}, 1),
        ({"type": "text", "autocomplete": "", "about": "mp email or mileageplus® number"}, 2),
        ({"type": "text", "autocomplete": "", "about": "ods-input-0"}, 3),
        ({"type": "text", "autocomplete": "", "about": "q search"}, None),
        ({"type": "text", "autocomplete": "", "about": "q"}, None),
        ({"type": "tel", "autocomplete": "one-time-code", "about": "otp enter code"}, None),
        ({"type": "checkbox", "autocomplete": "", "about": "remember me"}, None),
    ],
)
def test_which_box_wants_the_username(field, rank):
    assert fetching._username_rank(field) == rank


@pytest.mark.parametrize(
    ("text", "rejected"),
    [
        ("The username or password you entered is incorrect.", True),
        ("We can’t find that username and password. You can reset your password or try again.", True),
        ("That username and password combination doesn't match our records", True),
        ("The account information you entered is incorrect", True),
        ("Invalid username or password", True),
        ("We don’t recognize this device. Enter your password to continue.", False),
        ("Username\nPassword\nRemember me\nForgot username/password?\nSign in", False),
        ("Let’s make sure it’s you\nWe’ll text a one-time code to your phone.", False),
    ],
)
def test_what_counts_as_a_wrong_login(text, rejected):
    assert bool(fetching._REJECTED_WORDS.search(text)) is rejected


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
