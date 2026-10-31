"""Signs in to a program's website in Chrome and reads the balance, like you would by hand.

Each run restores the cookies and storage saved from the last run, so the site recognizes the
browser and usually skips the sign-in, or at least the security code. The first time, or when the
site asks for a code again, the run happens in a visible window so you can type the code.
"""

import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from award_wallet.providers import Provider

log = logging.getLogger(__name__)

# How long a visible window waits for you to enter a security code.
PERSON_TIMEOUT = 5 * 60
# How long a background run tries before giving up.
BACKGROUND_TIMEOUT = 60
# After signing in, how long a background run waits for the balance page before deciding the site
# wants a code.
CHALLENGE_GRACE = 20
POLL = 0.5

# Fields that hold a username, in the order we prefer them.
_USERNAME_SELECTORS = (
    "input[autocomplete='username']",
    "input[type='email']",
    "input[name*='user' i]",
    "input[id*='user' i]",
    "input[name*='login' i]",
    "input[id*='login' i]",
    "input[name*='email' i]",
    "input[name*='mileage' i]",
    "input[type='text']",
    "input[type='tel']",
    "input:not([type])",
)
_REJECTED_WORDS = re.compile(
    r"(incorrect|isn't right|is not right|doesn't match|don't recognize|do not recognize|invalid|wrong)"
    r".{0,60}(password|username|user id|sign[- ]?in|credentials|information)",
    re.IGNORECASE | re.DOTALL,
)


class FetchProblem(Exception):
    """A fetch that didn't produce a balance; the message is shown to you as is."""


class NeedsPerson(FetchProblem):
    """The site wants something only you can give, usually a security code."""


class LoginRejected(FetchProblem):
    """The site said the username or password is wrong."""


class ChromeMissing(FetchProblem):
    pass


@dataclass
class Fetched:
    balance: int
    session_state: dict[str, Any]


def browser_launcher(headless: bool):
    """Opens the browser runs use: your installed Google Chrome, or AW_BROWSER_PATH in tests."""
    from playwright.sync_api import Error, sync_playwright

    playwright = sync_playwright().start()
    options: dict[str, Any] = {
        "headless": headless,
        # Look like a normal Chrome, not one driven by a program.
        "ignore_default_args": ["--enable-automation"],
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if path := os.environ.get("AW_BROWSER_PATH"):
        options["executable_path"] = path
    else:
        options["channel"] = "chrome"
    try:
        browser = playwright.chromium.launch(**options)
    except Error as exc:
        playwright.stop()
        if "chrome" in str(exc).lower() and ("not found" in str(exc).lower() or "doesn't exist" in str(exc).lower()):
            raise ChromeMissing(
                "Award Wallet signs in through Google Chrome, which isn't installed. "
                "Get it at google.com/chrome, then refresh."
            ) from None
        raise
    return playwright, browser


def find_balance(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            digits = match.group(1).replace(",", "")
            if digits.isdigit():
                return int(digits)
    return None


def _visible(locator) -> Any | None:
    try:
        for index in range(min(locator.count(), 5)):
            candidate = locator.nth(index)
            if candidate.is_visible() and candidate.is_editable():
                return candidate
    except Exception:  # frames come and go while a page loads
        return None
    return None


def _frames(page):
    return [page.main_frame, *[frame for frame in page.frames if frame is not page.main_frame]]


def _login_fields(page):
    """The visible username and password fields, in whichever frame holds them."""
    for frame in _frames(page):
        password = _visible(frame.locator("input[type='password']"))
        username = None
        for selector in _USERNAME_SELECTORS:
            username = _visible(frame.locator(selector))
            if username:
                break
        if password or username:
            return frame, username, password
    return None, None, None


def _page_text(page) -> str:
    parts = []
    for frame in _frames(page):
        try:
            parts.append(frame.locator("body").inner_text(timeout=2000))
        except Exception:
            continue
    return "\n".join(parts)


def _where(url: str) -> str:
    """A page's address without the query or fragment, which can hold tokens: safe to log."""
    parts = urlsplit(url)
    return f"{parts.hostname or ''}{parts.path}"


def _same_site(url: str, target: str) -> bool:
    return urlsplit(url).hostname == urlsplit(target).hostname


def fetch_balance(
    provider: Provider,
    credentials: dict[str, str],
    session_state: dict[str, Any] | None,
    *,
    with_person: bool = False,
    launcher: Callable[[bool], tuple[Any, Any]] = browser_launcher,
    headless: bool | None = None,
    while_waiting: Callable[[Any], None] | None = None,
    screenshot_to: Path | None = None,
) -> Fetched:
    """Sign in if needed and read the balance.

    with_person opens a visible window and waits for you to finish any security check. Without
    it, a site asking for a code raises NeedsPerson. while_waiting is called on each poll while
    waiting for you (tests use it to play the person).
    """
    if not provider.supports_fetch:
        raise FetchProblem(f"Automatic fetching isn't available for {provider.name} yet.")
    assert provider.balance_url
    playwright, browser = launcher(not with_person if headless is None else headless)
    try:
        context = browser.new_context(storage_state=session_state, viewport={"width": 1200, "height": 900})
        page = context.new_page()
        page.goto(provider.balance_url, wait_until="domcontentloaded")
        try:
            balance = _sign_in_and_read(page, provider, credentials, with_person, while_waiting)
        except FetchProblem:
            if screenshot_to:
                _screenshot(page, screenshot_to)
            raise
        return Fetched(balance=balance, session_state=context.storage_state(indexed_db=True))
    finally:
        browser.close()
        playwright.stop()


def _screenshot(page, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path))
    except Exception:
        pass


def _sign_in_and_read(page, provider: Provider, credentials, with_person: bool, while_waiting) -> int:
    assert provider.balance_url
    started = time.monotonic()
    deadline = started + (PERSON_TIMEOUT if with_person else BACKGROUND_TIMEOUT)
    filled_username = filled_password = False
    signed_in_at: float | None = None
    last_visit = started
    last_where = ""

    while time.monotonic() < deadline:
        if (where := _where(page.url)) != last_where:
            log.info("%s: at %s", provider.key, where)
            last_where = where
        frame, username, password = _login_fields(page)
        on_balance_site = _same_site(page.url, provider.balance_url)

        if password is not None:
            if not filled_password:
                if username is not None and not username.input_value():
                    username.fill(credentials.get("username", ""))
                password.fill(credentials.get("password", ""))
                password.press("Enter")
                log.info("%s: submitted the login", provider.key)
                filled_username = filled_password = True
                signed_in_at = time.monotonic()
                time.sleep(POLL * 2)
                continue
            # The sign-in form is back after we submitted: wrong login, or a site hiccup.
            if _REJECTED_WORDS.search(_page_text(page)):
                log.info("%s: the site rejected the login", provider.key)
                raise LoginRejected(f"{provider.name} didn't accept the saved username or password. Save it again.")
        else:
            if on_balance_site:
                balance = find_balance(_page_text(page), provider.balance_patterns)
                if balance is not None:
                    log.info("%s: found the balance", provider.key)
                    return balance
            if username is not None and not filled_username and _looks_like_sign_in(page):
                # Sites that ask for the username first and the password on the next screen.
                username.fill(credentials.get("username", ""))
                username.press("Enter")
                log.info("%s: submitted the username", provider.key)
                filled_username = True
                time.sleep(POLL * 2)
                continue
            if username is None and not on_balance_site and time.monotonic() - last_visit > 8:
                # Signed in, but the site landed somewhere else: go to the balance page. (A page with
                # a box to type in, like a security code, is left alone.)
                last_visit = time.monotonic()
                log.info("%s: going to the balance page", provider.key)
                try:
                    page.goto(provider.balance_url, wait_until="domcontentloaded")
                except Exception as exc:
                    log.info("%s: couldn't open the balance page: %s", provider.key, exc)
                continue

        if not with_person and signed_in_at and time.monotonic() - signed_in_at > CHALLENGE_GRACE:
            raise NeedsPerson(f"{provider.name} wants to confirm it's you. Click Sign in to enter the code.")
        if with_person and while_waiting:
            while_waiting(page)
        time.sleep(POLL)

    if with_person:
        raise NeedsPerson(f"The {provider.name} window timed out before the sign-in finished. Try again.")
    if not filled_password:
        raise FetchProblem(
            f"Couldn't find your {provider.name} balance on its page. The site may have changed; "
            "a screenshot was saved for checking."
        )
    raise NeedsPerson(f"{provider.name} wants to confirm it's you. Click Sign in to enter the code.")


def _looks_like_sign_in(page) -> bool:
    # A username box on the program's own sign-in pages, not a search box somewhere else.
    parts = urlsplit(page.url)
    where = f"{parts.path}#{parts.fragment}".lower()
    return any(word in where for word in ("login", "logon", "signin", "sign-in", "sign_in"))
