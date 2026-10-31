import glob
import os

import pytest
from fakebank import CODE, PASSWORD, USERNAME, FakeBank, serve

from award_wallet import fetching
from award_wallet.providers import Provider

CHROME = next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")), None)
pytestmark = pytest.mark.skipif(CHROME is None and "AW_BROWSER_PATH" not in os.environ, reason="no browser")


@pytest.fixture(autouse=True)
def browser_path(monkeypatch):
    if CHROME and "AW_BROWSER_PATH" not in os.environ:
        monkeypatch.setenv("AW_BROWSER_PATH", CHROME)
    monkeypatch.setattr(fetching, "CHALLENGE_GRACE", 4)
    monkeypatch.setattr(fetching, "BACKGROUND_TIMEOUT", 20)


def make_site(**options):
    bank = FakeBank(**options)
    server, thread, url = serve(bank)

    class Site(Provider):
        key = name = program = "fake"
        unit = "miles"
        balance_url = f"{url}/account"
        balance_patterns = (r"(\d[\d,]*)\s*miles\b",)

    return bank, Site(), server


LOGIN = {"username": USERNAME, "password": PASSWORD}


def type_code(page):
    box = page.locator("input[name=code]")
    if box.count() and box.is_visible() and not box.input_value():
        box.fill(CODE)
        box.press("Enter")


@pytest.mark.parametrize("options", [{}, {"two_step": True}, {"in_iframe": True}])
def test_first_sign_in_needs_the_person_then_runs_quietly(options):
    bank, site, server = make_site(**options)
    try:
        # In the background the site's code request stops the run.
        with pytest.raises(fetching.NeedsPerson):
            fetching.fetch_balance(site, LOGIN, None)

        # With the person there (here, type_code plays them) it signs in and reads the balance.
        first = fetching.fetch_balance(site, LOGIN, None, with_person=True, headless=True, while_waiting=type_code)
        assert first.balance == 52300

        # Later runs reuse the saved browser state: no code, even after the site's session ends.
        bank.expire_sessions()
        bank.balance = 61000
        asked = bank.codes_asked
        again = fetching.fetch_balance(site, LOGIN, first.session_state)
        assert again.balance == 61000
        assert bank.codes_asked == asked
    finally:
        server.should_exit = True


def test_wrong_password_is_reported(tmp_path):
    bank, site, server = make_site()
    try:
        with pytest.raises(fetching.LoginRejected):
            fetching.fetch_balance(
                site, {"username": USERNAME, "password": "nope"}, None, screenshot_to=tmp_path / "shot.png"
            )
        assert (tmp_path / "shot.png").exists()
    finally:
        server.should_exit = True


def test_find_balance_reads_the_first_match():
    assert fetching.find_balance("Earn 2X miles\nRewards\n52,300 Miles", (r"(\d[\d,]*)\s*miles\b",)) == 52300
    assert fetching.find_balance("nothing here", (r"(\d[\d,]*)\s*miles\b",)) is None
