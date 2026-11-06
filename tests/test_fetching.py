import base64
import glob
import json
import os

import pytest
from fakebank import CODE, PASSWORD, USERNAME, FakeBank, serve

from award_wallet import fetching
from award_wallet.providers import Provider
from award_wallet.sign_in_view import SignInView

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
    return fetching.fetch_balance(site, LOGIN, profile, **options)


def click(locator) -> dict:
    """A click in the middle of something on the page, as the app's window sends it."""
    box = locator.bounding_box()
    return {"kind": "click", "x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}


def type_code(view):
    """You, in the app's window: ask for the code by text if the site lets you choose, then type
    it, all by clicking and typing on the picture of the page. (The test looks at the page itself
    to know where on the picture things are.)"""

    def you(page):
        if not view.status()["picture"]:
            return  # nothing on screen yet
        try:
            box = page.locator("input[name=code]")
            if box.count() and box.is_visible():
                if not box.input_value():
                    view.send([click(box), {"kind": "text", "text": CODE}, {"kind": "key", "key": "Enter"}])
                return
            text = page.get_by_role("button", name="Get a text")
            if text.count() and text.is_visible():
                view.send([click(text)])
        except Exception:  # the page is changing
            pass

    return you


def sign_in(provider, profile, you=type_code, **options):
    """Sign in with you at the app's window."""
    view = SignInView(provider.name)
    return fetch(provider, profile, view=view, while_waiting=you(view), **options), view


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

    # A refresh shows nothing: it stops at the site's code request, and says to click Sign in.
    with pytest.raises(fetching.NeedsPerson, match="Click Sign in"):
        fetch(provider, profile)

    # Sign in shows the page in the app's window, where you type the code (type_code plays you).
    balance, view = sign_in(provider, profile)
    assert balance == 52300
    assert bank.codes_asked == 2
    assert view.picture().startswith(b"\xff\xd8")  # a JPEG of the page
    assert view.status()["width"] > 0 and view.status()["height"] > 0

    # Later refreshes use the same Chrome profile, so the site knows this browser: no code, even
    # after the site's session ends and the login has to be typed again.
    bank.expire_sessions()
    bank.balance = 61000
    assert fetch(provider, profile) == 61000
    assert bank.codes_asked == 2
    assert bank.searches == []  # the search box never got the username


@needs_browser
def test_a_username_box_on_the_account_page_is_filled(site, tmp_path, caplog):
    # United shows "Email or MileagePlus number" right on its account page, with a Continue button.
    bank, provider = site(sign_in_on_page=True)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 52300
    assert "submitted the username" in caplog.text and "clicked the form's button" in caplog.text
    assert bank.searches == []


@needs_browser
def test_an_email_box_that_isnt_the_login_is_left_alone(site, tmp_path, monkeypatch):
    # The balance takes a while to show, and the page has a newsletter's email box meanwhile.
    monkeypatch.setattr(fetching, "SCROLL_EVERY", 0.5)
    bank, provider = site(shows="below", newsletter=True)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 52300
    assert bank.subscribed == [] and bank.searches == []


@needs_browser
def test_a_refresh_that_needs_you_stops_and_says_why(site, tmp_path, caplog, monkeypatch):
    # Chase asks on its dashboard's own address, where the run otherwise keeps looking for the
    # number: the refresh stops right away instead, with a screenshot, and nothing pops up.
    monkeypatch.setattr(fetching, "CHALLENGE_GRACE", 60)
    bank, provider = site(confirm_in_place=True)
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        with pytest.raises(fetching.NeedsPerson) as stopped:
            fetch(provider, tmp_path / "profile", screenshot_to=tmp_path / "fake.png")
    assert str(stopped.value) == (
        "fake wants to confirm it's you, usually only the first time. Click Sign in to do it; "
        "after that, refreshes run on their own."
    )
    assert "the site asks to confirm it's you" in caplog.text
    assert (tmp_path / "fake.png").exists()


@needs_browser
def test_while_you_sign_in_the_app_says_what_the_site_wants(site, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "CHALLENGE_GRACE", 60)
    bank, provider = site(confirm_in_place=True)

    def you_after_the_note(view):
        you = type_code(view)
        return lambda page: you(page) if view.note else None

    balance, view = sign_in(provider, tmp_path / "profile", you=you_after_the_note)
    assert balance == 52300
    assert view.note == (
        "fake wants to confirm it's you, usually only the first time. Do what it asks below; "
        "after that, refreshes run on their own."
    )


def test_a_sign_in_runs_in_the_same_hidden_chrome_as_a_refresh(site, tmp_path):
    bank, provider = site()
    launched = []

    def launcher(profile):
        launched.append(profile)
        raise RuntimeError("enough")

    for view in (None, SignInView("fake")):
        with pytest.raises(RuntimeError):
            fetching.fetch_balance(provider, LOGIN, tmp_path / "p", view=view, launcher=launcher)
    assert launched == [tmp_path / "p"] * 2
    assert fetching._launch_options()["headless"] is True


@needs_browser
def test_once_you_click_the_app_leaves_the_page_to_you(site, tmp_path, monkeypatch):
    # Time to click before the app would type: from then on it types nothing, so a saved login
    # that's out of date isn't sent behind your back.
    monkeypatch.setattr(fetching, "FORM_SETTLE", 3)
    bank, provider = site()
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]

    def you(view):
        type_login = you_sign_in(view)

        def act(page):
            if not view.status()["picture"]:
                return
            if not act.clicked:
                act.clicked = True
                view.send([{"kind": "click", "x": 1, "y": 1}])
            else:
                type_login(page)

        act.clicked = False
        return act

    view = SignInView("fake")
    balance = fetching.fetch_balance(
        provider,
        {"username": USERNAME, "password": "out of date"},
        tmp_path / "profile",
        view=view,
        seed_cookies=cookies,
        while_waiting=you(view),
    )
    assert balance == 52300
    assert bank.logins == 1  # yours


@needs_browser
def test_you_can_scroll_the_page(site, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "SCROLL_EVERY", 999)  # the app doesn't scroll by itself here
    bank, provider = site(shows="below")
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]

    def you(view):
        def scroll(page):
            status = view.status()
            if status["picture"] and page.url.endswith("/account"):
                middle = {"x": status["width"] / 2, "y": status["height"] / 2}
                view.send([{"kind": "scroll", **middle, "dx": 0, "dy": 1500}])

        return scroll

    balance, view = sign_in(provider, tmp_path / "profile", you=you, seed_cookies=cookies)
    assert balance == 52300


@needs_browser
def test_a_sign_in_you_stop_ends_right_away(site, tmp_path):
    bank, provider = site()

    def you_stop(view):
        return lambda page: view.stop()

    with pytest.raises(fetching.NeedsPerson, match="You stopped the sign-in to fake"):
        sign_in(provider, tmp_path / "profile", you=you_stop)


@needs_browser
def test_hidden_chrome_tells_sites_it_is_chrome(site, tmp_path):
    # Chrome's hidden mode calls itself HeadlessChrome, which some sites turn away.
    bank, provider = site()
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 52300
    assert bank.user_agents and all("Chrome/" in agent and "Headless" not in agent for agent in bank.user_agents)


@needs_browser
def test_the_login_is_typed_a_key_at_a_time(site, tmp_path):
    # Capital One turns down a password that went into its box all at once.
    bank, provider = site(needs_keys=True)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 52300
    assert bank.logins == 1


def you_sign_in(view):
    """You, in the app's window, typing your login over whatever the site shows."""

    def you(page):
        if not view.status()["picture"]:
            return
        try:
            box = page.locator("input[type=password]")
            if box.count() and box.is_visible() and not box.input_value():
                events = []
                name = page.locator("input[name=username]")
                if name.count() and name.is_visible() and not name.input_value():
                    events += [click(name), {"kind": "text", "text": USERNAME}]
                events += [click(box), {"kind": "text", "text": PASSWORD}, {"kind": "key", "key": "Enter"}]
                view.send(events)
        except Exception:  # the page is changing
            pass

    return you


@needs_browser
@pytest.mark.parametrize("type_login", [True, False])
def test_a_login_you_fix_while_signing_in_is_kept(site, tmp_path, type_login):
    bank, provider = site()
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    kept = []
    view = SignInView("fake")
    you = you_sign_in(view)

    balance = fetching.fetch_balance(
        provider,
        {"username": USERNAME, "password": "old password"},
        tmp_path / "profile",
        view=view,
        type_login=type_login,
        seed_cookies=cookies,
        while_waiting=lambda page: you(page) if view.note else None,
        on_new_login=kept.append,
    )
    assert balance == 52300
    assert view.note == "fake didn't take the saved login. Sign in below, and Award Wallet keeps the login that works."
    assert kept == [{"username": USERNAME, "password": PASSWORD}]
    assert bank.logins == (2 if type_login else 1)  # the saved login is tried once at most


@needs_browser
def test_a_login_that_already_worked_is_not_kept_again(site, tmp_path):
    bank, provider = site()
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    kept = []
    balance, view = sign_in(provider, tmp_path / "profile", seed_cookies=cookies, on_new_login=kept.append)
    assert balance == 52300 and kept == []


@needs_browser
def test_a_login_the_site_cleared_is_typed_once_more(site, tmp_path, caplog):
    bank, provider = site(clears_form_once=True)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 52300
    assert bank.logins == 2
    assert "the site cleared the login" in caplog.text


@needs_browser
def test_a_form_that_comes_back_with_a_message_is_left_to_you(site, tmp_path):
    # Whatever the site said, the app doesn't know it: it never types the password again over it.
    bank, provider = site(clears_form_once=True, says_once="Something about your sign-in needs attention.")
    with pytest.raises(fetching.NeedsPerson):
        fetch(provider, tmp_path / "profile")
    assert bank.logins == 1


@needs_browser
def test_a_wrong_password_is_typed_only_once(site, tmp_path):
    bank, provider = site(clears_form_once=True)
    with pytest.raises(fetching.LoginRejected):
        fetching.fetch_balance(provider, {"username": USERNAME, "password": "nope"}, tmp_path / "p")
    assert bank.logins == 2  # the one the site cleared, and one that it said was wrong


@needs_browser
def test_cookies_kept_by_older_versions_carry_over(site, tmp_path):
    bank, provider = site()
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 52300
    assert bank.codes_asked == 0


@needs_browser
def test_a_balance_counts_once_it_stops_changing(site, tmp_path):
    bank, provider = site(shows="counting", balance=163918)
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 163918


@needs_browser
def test_scrolls_to_a_balance_that_loads_when_seen(site, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "SCROLL_EVERY", 0.5)
    bank, provider = site(shows="below")
    bank.trusted.add("known-mac")
    cookies = [{"name": "device", "value": "known-mac", "domain": "127.0.0.1", "path": "/"}]
    assert fetch(provider, tmp_path / "profile", seed_cookies=cookies) == 52300


@needs_browser
def test_the_sites_own_error_is_passed_on(site, tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "TROUBLE_GRACE", 1)
    bank, provider = site(shows="trouble")
    with pytest.raises(fetching.FetchProblem, match="fake says: “We can’t access your account information right now"):
        sign_in(provider, tmp_path / "profile")


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
def test_a_sign_in_waits_for_you(site, tmp_path, monkeypatch):
    # You might be signing in on that very page: only your own time limit ends the sign-in.
    monkeypatch.setattr(fetching, "READ_TIMEOUT", 1)
    monkeypatch.setattr(fetching, "PERSON_TIMEOUT", 4)
    bank, provider = site(shows="empty")
    with pytest.raises(fetching.NeedsPerson, match="The sign-in to fake timed out before it finished"):
        sign_in(provider, tmp_path / "profile")


@needs_browser
def test_the_log_shows_each_step_but_never_the_login(site, tmp_path, caplog):
    bank, provider = site()
    with caplog.at_level("INFO", logger="award_wallet.fetching"):
        with pytest.raises(fetching.NeedsPerson):
            fetch(provider, tmp_path / "profile")
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
            screenshot_to=tmp_path / "shot.png",
        )
    assert (tmp_path / "shot.png").exists()


def test_chromes_own_prompts_are_turned_off(tmp_path):
    preferences = tmp_path / "Default" / "Preferences"
    fetching.quiet_profile(tmp_path)
    settings = json.loads(preferences.read_text())
    assert settings["credentials_enable_service"] is False
    assert settings["profile"] == {"password_manager_enabled": False, "exit_type": "Normal", "exited_cleanly": True}
    assert settings["autofill"] == {"enabled": False, "profile_enabled": False, "credit_card_enabled": False}

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
        # Capital One, 2026-11-06.
        ("We didn't recognize that info\nDouble-check your username and password and try signing in again.", True),
        ("We didn’t recognize this device, so we need to confirm it’s you.", False),
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


# What a saved screenshot shows at three spots: the box on the page, the box in the frame, and the
# page around them.
_PIXELS = """() => new Promise((done) => {
  const image = document.images[0];
  const read = () => {
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const pen = canvas.getContext("2d");
    pen.drawImage(image, 0, 0);
    const at = (x, y) => Array.from(pen.getImageData(x, y, 1, 1).data.slice(0, 3));
    done([at(120, 40), at(120, 120), at(500, 300)]);
  };
  if (image.complete) read(); else image.onload = read;
})"""


@needs_browser
def test_a_screenshot_blacks_out_what_was_typed(tmp_path):
    # Screenshots go in the Diagnostics folder, which is meant to be safe to send.
    playwright, context = fetching.browser_launcher(tmp_path / "profile")
    try:
        page = context.pages[0] if context.pages else context.new_page()
        box = "position:absolute;left:20px;width:200px;height:40px"
        page.set_content(
            "<body style='margin:0;background:#fff'>"
            f"<input style='{box};top:20px' value='rafael'>"
            f"<iframe style='{box};top:100px;border:0' srcdoc=\"<body style='margin:0'>"
            "<input style='width:200px;height:40px' value='123456'>\"></iframe></body>"
        )
        shot = tmp_path / "shot.png"
        fetching._screenshot(page, shot)
        viewer = context.new_page()
        viewer.set_content(f"<img src='data:image/png;base64,{base64.b64encode(shot.read_bytes()).decode()}'>")
        on_page, in_frame, around = viewer.evaluate(_PIXELS)
    finally:
        context.close()
        playwright.stop()
    assert on_page == in_frame == [0, 0, 0]
    assert around == [255, 255, 255]
