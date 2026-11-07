"""The sign-in page itself, in a browser standing in for the app's window: you click and type on
the picture of the site's page, and the hidden Chrome signs in."""

import glob
import os
import socket
import threading
import time

import pytest
import uvicorn
from fakebank import CODE, PASSWORD, USERNAME, FakeBank, serve

from milestash import fetching
from milestash.providers.capital_one import CapitalOne
from milestash.web import create_app

from conftest import LAUNCH_TOKEN

CHROME = next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")), None)
needs_browser = pytest.mark.skipif(CHROME is None and "MILESTASH_BROWSER_PATH" not in os.environ, reason="no browser")


def serve_app(app):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    return server, f"http://127.0.0.1:{port}"


@needs_browser
def test_you_sign_in_from_the_apps_window(settings, monkeypatch):
    from playwright.sync_api import sync_playwright

    browser_path = os.environ.get("MILESTASH_BROWSER_PATH") or CHROME
    monkeypatch.setenv("MILESTASH_BROWSER_PATH", browser_path)
    monkeypatch.setattr(fetching, "CHALLENGE_GRACE", 4)
    monkeypatch.setattr(fetching, "QUIET_TIMEOUT", 20)
    # Capital One, played by the pretend bank: it asks to confirm it's you until it knows the browser.
    bank = FakeBank(confirm_in_place=True)
    bank_server, _, bank_url = serve(bank)

    class Site(CapitalOne):
        balance_url = f"{bank_url}/account"
        balance_patterns = (r"(\d[\d,]*)\s*miles\b",)

    app = create_app(settings.model_copy(update={"auto_fetch": True}))
    app.state.refresher._fetch = lambda provider, *args, **options: fetching.fetch_balance(Site(), *args, **options)
    app_server, app_url = serve_app(app)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=browser_path)
            window = browser.new_page(viewport={"width": 1100, "height": 1000})
            window.goto(f"{app_url}/?token={LAUNCH_TOKEN}")
            window.goto(f"{app_url}/accounts/new?provider=capital_one")
            window.fill("input[name=credential_username]", USERNAME)
            window.fill("input[name=credential_password]", PASSWORD)
            window.get_by_role("button", name="Link").click()

            # The refresh after linking shows nothing and stops at the code request: Sign in.
            window.goto(f"{app_url}/")
            window.get_by_role("button", name="Sign in").click(timeout=60_000)
            window.wait_for_url("**/sign-in?back=dashboard")
            picture = window.locator("#screen-picture")
            window.locator(".sign-in-asks").wait_for(timeout=60_000)
            assert "Capital One wants to confirm it's you" in window.locator("#sign-in-note").inner_text()
            assert picture.is_visible()

            # Where things sit on the site's page, from the same page in another tab, to know where
            # to click on the picture.
            status_url = window.url.split("?")[0] + "/status"
            status = window.evaluate("(url) => fetch(url).then((answer) => answer.json())", status_url)
            reference = browser.new_page(viewport={"width": int(status["width"]), "height": int(status["height"])})
            reference.goto(f"{bank_url}/account?step=confirm")

            def click_on_the_picture(target):
                spot, shown = target.bounding_box(), picture.bounding_box()
                scale = shown["width"] / status["width"]
                window.mouse.click(
                    shown["x"] + (spot["x"] + spot["width"] / 2) * scale,
                    shown["y"] + (spot["y"] + spot["height"] / 2) * scale,
                )

            get_a_text = reference.get_by_role("button", name="Get a text")
            click_on_the_picture(get_a_text)
            get_a_text.click()
            window.wait_for_timeout(1500)
            click_on_the_picture(reference.locator("input[name=code]"))
            window.keyboard.type(CODE)
            window.keyboard.press("Enter")

            # Signed in: the balance is read and the window goes back to the dashboard.
            window.wait_for_url(f"{app_url}/", timeout=60_000)
            window.get_by_text("52,300").wait_for(timeout=10_000)
            assert "Up to date" in window.content()
            codes = bank.codes_asked

            # From now on refreshes need nothing, even once the site's session has ended.
            bank.expire_sessions()
            bank.balance = 61000
            window.get_by_role("button", name="Refresh now").click()
            window.get_by_text("61,000").wait_for(timeout=60_000)
            assert bank.codes_asked == codes
            browser.close()
    finally:
        app_server.should_exit = True
        bank_server.should_exit = True
