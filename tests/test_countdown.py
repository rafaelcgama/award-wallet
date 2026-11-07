"""The expiration countdown in the app's pages, run in a real browser with its clock moved on."""

import glob
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import milestash

CHROME = os.environ.get("MILESTASH_BROWSER_PATH") or next(
    iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")), None
)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no browser")
APP_JS = Path(milestash.__file__).parent / "web" / "static" / "app.js"


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME)
        context = browser.new_context(timezone_id="America/Sao_Paulo")
        yield context.new_page()
        browser.close()


def test_the_countdown_goes_down_by_one_each_day_while_the_window_stays_open(page):
    # 23:59 in Sao Paulo on Nov 7: the miles expire in 90 days, on Feb 5.
    page.clock.install(time=datetime(2026, 11, 8, 2, 59, tzinfo=UTC))
    page.set_content(
        '<!doctype html><body><span class="countdown" data-expires-on="2027-02-05">in 90 days</span></body>'
    )
    page.add_script_tag(path=APP_JS)
    countdown = page.locator(".countdown")
    assert countdown.text_content() == "in 90 days"
    page.clock.run_for("02:00")  # past midnight
    assert countdown.text_content() == "in 89 days"
    page.clock.run_for("24:00:00")
    assert countdown.text_content() == "in 88 days"
    # The last days, through a Mac that slept: the count is right on the next minute after it wakes.
    for moment, said in (
        (datetime(2027, 2, 4, 15, tzinfo=UTC), "tomorrow"),
        (datetime(2027, 2, 5, 15, tzinfo=UTC), "today"),
        (datetime(2027, 2, 6, 15, tzinfo=UTC), "already expired"),
    ):
        page.clock.set_system_time(moment)
        page.clock.run_for("01:00")
        assert countdown.text_content() == said
