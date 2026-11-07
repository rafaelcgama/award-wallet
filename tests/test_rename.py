"""Renaming a program in place, in a real browser on the app's own pages."""

import glob
import os
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import uvicorn

from conftest import LAUNCH_TOKEN, link

CHROME = os.environ.get("AW_BROWSER_PATH") or next(
    iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")), None
)
pytestmark = pytest.mark.skipif(CHROME is None, reason="no browser")


@pytest.fixture
def window(app, client):
    """The app's window in a real browser: the app served the way the Mac app serves it, with its
    headers and its script, and signed in with the launch link."""
    from playwright.sync_api import sync_playwright

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # The client already started the app; this only serves it.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME)
        page = browser.new_page(base_url=f"http://127.0.0.1:{port}")
        page.goto(f"/?token={LAUNCH_TOKEN}")
        yield page
        browser.close()
    server.should_exit = True
    thread.join()


def test_double_clicking_the_title_renames_the_program(client, window):
    account_id = link(client, "american", label="American Airlines")
    window.goto(f"/accounts/{account_id}")
    title = window.locator(".rename .rename-text")
    box = window.locator(".rename input[name=label]")
    assert not box.is_visible()

    title.dblclick()
    assert box.is_visible()
    assert box.evaluate("box => box === document.activeElement && box.selectionEnd - box.selectionStart")
    # Esc leaves the name as it was.
    box.fill("Something else")
    box.press("Escape")
    assert not box.is_visible()
    assert title.text_content() == "American Airlines"

    title.dblclick()
    box.fill("AAdvantage")
    with window.expect_navigation():
        box.press("Enter")
    assert urlsplit(window.url).path == f"/accounts/{account_id}"
    assert window.locator(".rename .rename-text").text_content() == "AAdvantage"
    # The card on the main page shows the new name.
    window.goto("/")
    assert window.locator(".program-card .program").text_content() == "AAdvantage"


def test_clicking_away_keeps_what_you_typed(client, window):
    account_id = link(client, "united")
    window.goto(f"/accounts/{account_id}")
    window.locator(".rename .rename-text").dblclick()
    window.locator(".rename input[name=label]").fill("Work miles")
    with window.expect_navigation():
        window.locator(".balance-empty").click()
    assert window.locator(".rename .rename-text").text_content() == "Work miles"
