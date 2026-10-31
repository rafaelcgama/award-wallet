"""Signs in to a program's website in Chrome and reads the balance, like you would by hand.

Each program has its own Chrome profile in the app's data folder, used for every run, so the site
sees the same browser every time and remembers it the way your own Chrome is remembered: after
the first sign-in it usually skips the security code. A refresh runs in a minimized window; if
the site asks for something only you can give, like a code, the window comes up and waits for you.
"""

import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from award_wallet.providers import Provider

log = logging.getLogger(__name__)

# How long a window that's up for you waits for you to finish.
PERSON_TIMEOUT = 5 * 60
# How long a refresh tries in its minimized window before bringing it up for you.
QUIET_TIMEOUT = 60
# After the login is submitted, how long a refresh waits for the balance page before deciding the
# site wants a code.
CHALLENGE_GRACE = 20
# How long the balance page gets to show the number before the run gives up.
READ_TIMEOUT = 45
# How long a site's own error message ("we can't access your account right now") has to stay up
# before the run stops and passes it on.
TROUBLE_GRACE = 10
# A balance counts once it reads the same twice this far apart: some pages count up to it or show
# a placeholder first.
STEADY = 1.0
POLL = 0.5
# How far up the page's boxes a label is followed to find its number.
MAX_CLIMB = 10
# While the balance page doesn't show the number, scroll a screen further this often: some pages
# only load a box when it comes into view.
SCROLL_EVERY = 3
WINDOW_SIZE = (1200, 900)

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
# A site saying it can't show the account right now: one sentence of it, to pass on.
_SITE_TROUBLE = re.compile(
    r"[^.!\n]*(?:can.t access your account|temporarily unavailable|technical difficult|something went wrong"
    r"|unable to (?:display|load|show) your)[^.!\n]*[.!]?",
    re.IGNORECASE,
)

# Runs in the page. Finds the number a label names, the way you'd read it on screen: the label and
# its number sit together in a box, like "163,918" above "Ultimate Rewards® points", while other
# boxes nearby hold other programs' numbers. Looks inside web components too, which the page's
# plain text leaves out. A number only counts if it stands on its own (a balance, not the "5" in
# "earn 5 points per dollar").
_READ_BY_LABEL = r"""
([source, maxClimb]) => {
  const label = new RegExp(source, "i");
  const value = /^(\d{1,3}(?:,\d{3})+|\d+)\s*(?:pts|points|miles)?\s*[*†‡¹²³]?$/i;
  const skip = new Set(["head", "script", "style", "noscript", "template", "svg"]);
  const parent = new Map();
  const text = new Map();
  const order = [];

  // Children as drawn on screen: a web component's own content, and what fills its slots.
  const childrenOf = (node) => {
    if (node.shadowRoot) return node.shadowRoot.childNodes;
    if (node.localName === "slot") {
      const assigned = node.assignedNodes({ flatten: true });
      if (assigned.length) return assigned;
    }
    return node.childNodes;
  };

  const visit = (node, up) => {
    if (node.nodeType === Node.TEXT_NODE) return node.data;
    if (node.nodeType !== Node.ELEMENT_NODE || skip.has(node.localName)) return "";
    if (node.localName === "br") return "\n";
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return "";
    parent.set(node, up);
    order.push(node);
    let joined = "";
    for (const child of childrenOf(node)) joined += visit(child, node);
    text.set(node, joined.replace(/\s+/g, " ").trim());
    const inline = style.display.startsWith("inline") || style.display === "contents";
    return inline ? joined : `\n${joined}\n`;
  };
  visit(document.body, null);

  // The innermost elements whose text matches, not every box around them.
  const innermost = (test) => {
    const matches = order.filter((element) => test(text.get(element)));
    const outer = new Set();
    for (const element of matches) {
      for (let at = parent.get(element); at; at = parent.get(at)) outer.add(at);
    }
    return matches.filter((element) => !outer.has(element));
  };
  const labels = innermost((words) => label.test(words));
  if (!labels.length) return { number: null, seen: "no label" };
  const values = innermost((words) => value.test(words));
  const inside = (element, box) => {
    for (let at = element; at; at = parent.get(at)) if (at === box) return true;
    return false;
  };

  const found = [];
  let crowded = false;
  for (const element of labels) {
    // The label and its number in one piece of text, like "163,918 Ultimate Rewards points".
    const rest = text.get(element).replace(label, "").replace(/^[\s:]+|[\s:]+$/g, "");
    const own = rest.match(value);
    if (own) {
      found.push({ distance: 0, number: own[1] });
      continue;
    }
    // Otherwise the nearest box around the label that holds a number decides.
    let box = element;
    for (let distance = 0; box && distance <= maxClimb; distance++, box = parent.get(box)) {
      const numbers = new Set(values.filter((v) => inside(v, box)).map((v) => text.get(v).match(value)[1]));
      if (!numbers.size) continue;
      if (numbers.size === 1) found.push({ distance, number: [...numbers][0] });
      else crowded = true;
      break;
    }
  }
  if (!found.length) return { number: null, seen: crowded ? "several numbers next to it" : "no number next to it" };
  const nearest = Math.min(...found.map((item) => item.distance));
  const numbers = new Set(found.filter((item) => item.distance === nearest).map((item) => item.number));
  if (numbers.size > 1) return { number: null, seen: "different numbers next to it in different places" };
  return { number: [...numbers][0], seen: "found" };
}
"""


class FetchProblem(Exception):
    """A fetch that didn't produce a balance; the message is shown to you as is."""


class NeedsPerson(FetchProblem):
    """The site wants something only you can give, usually a security code."""


class LoginRejected(FetchProblem):
    """The site said the username or password is wrong."""


class ChromeMissing(FetchProblem):
    pass


def browser_launcher(profile: Path, headless: bool):
    """Opens Chrome with the program's own profile: your installed Google Chrome, or
    AW_BROWSER_PATH in tests. Returns Playwright and the browser context."""
    from playwright.sync_api import Error, sync_playwright

    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    width, height = WINDOW_SIZE
    options: dict[str, Any] = {
        "headless": headless,
        # Look like a normal Chrome, not one driven by a program, and keep the cookies encrypted
        # with the Mac's Keychain like your own Chrome does (Playwright would use a fake one).
        "ignore_default_args": ["--enable-automation", "--use-mock-keychain"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            f"--window-size={width},{height}",
            "--disk-cache-size=52428800",
        ],
    }
    if headless:
        options["viewport"] = {"width": width, "height": height}
    else:
        # The page fills the window, like any Chrome window.
        options["no_viewport"] = True
    if path := os.environ.get("AW_BROWSER_PATH"):
        options["executable_path"] = path
    else:
        options["channel"] = "chrome"
    try:
        context = playwright.chromium.launch_persistent_context(str(profile), **options)
    except Error as exc:
        playwright.stop()
        message = str(exc).lower()
        if "chrome" in message and ("not found" in message or "doesn't exist" in message):
            raise ChromeMissing(
                "Award Wallet signs in through Google Chrome, which isn't installed. "
                "Get it at google.com/chrome, then refresh."
            ) from None
        raise
    return playwright, context


def find_balance(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            digits = match.group(1).replace(",", "")
            if digits.isdigit():
                return int(digits)
    return None


def read_by_label(page, labels: tuple[str, ...]) -> tuple[int | None, str]:
    """The number one of the labels names on the page, and what was seen, for the log."""
    seen = "no label on the page yet"
    for label in labels:
        for frame in _frames(page):
            try:
                found = frame.evaluate(_READ_BY_LABEL, [label, MAX_CLIMB])
            except Exception:  # frames come and go while a page loads
                continue
            if found["number"] is not None:
                return int(found["number"].replace(",", "")), "found the label and its number"
            if found["seen"] != "no label":
                seen = f"found the label but {found['seen']}"
    return None, seen


def read_balance(page, provider: Provider) -> tuple[int | None, str]:
    """The balance on the page, if it's there yet, and what was seen, for the log."""
    seen = "no balance on the page yet"
    if provider.balance_labels:
        balance, seen = read_by_label(page, provider.balance_labels)
        if balance is not None:
            return balance, seen
    if provider.balance_patterns:
        balance = find_balance(_page_text(page), provider.balance_patterns)
        if balance is not None:
            return balance, "found the balance in the page's text"
    return None, seen


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


def _site_trouble(page) -> str | None:
    """The site's own message saying it can't show the account right now, if it shows one."""
    if match := _SITE_TROUBLE.search(_page_text(page)):
        return " ".join(match.group(0).split())[:200]
    return None


def _where(url: str) -> str:
    """A page's address without the query or fragment, which can hold tokens: safe to log."""
    parts = urlsplit(url)
    return f"{parts.hostname or ''}{parts.path}"


def _site(url: str) -> str:
    """The site a page belongs to: secure07c.chase.com and secure.chase.com are both chase.com."""
    host = urlsplit(url).hostname or ""
    if "." not in host or host.replace(".", "").isdigit():  # localhost or an IP address, in tests
        return host
    return ".".join(host.split(".")[-2:])


def _same_site(url: str, target: str) -> bool:
    return bool(_site(url)) and _site(url) == _site(target)


def _looks_like_sign_in(url: str) -> bool:
    # A username box on the program's own sign-in pages, not a search box somewhere else.
    parts = urlsplit(url)
    where = f"{parts.path}#{parts.fragment}".lower()
    return any(word in where for word in ("login", "logon", "signin", "sign-in", "sign_in"))


def _at_balance_page(url: str, balance_url: str) -> bool:
    return (
        _same_site(url, balance_url)
        and urlsplit(url).path.rstrip("/") == urlsplit(balance_url).path.rstrip("/")
        and not _looks_like_sign_in(url)
    )


class _Window:
    """The run's Chrome window: minimized while a refresh works quietly, brought up when you're
    needed. In tests there's no window (headless), and only the state is kept."""

    def __init__(self, context, page, headless: bool):
        self._page = page
        self._cdp = None
        self.shown = False
        if not headless:
            try:
                self._cdp = context.new_cdp_session(page)
            except Exception as exc:
                log.info("Can't control the Chrome window: %s", exc)

    def hide(self) -> None:
        self._set("minimized")
        self.shown = False

    def show(self) -> None:
        self._set("normal")
        try:
            self._page.bring_to_front()
        except Exception:
            pass
        self.shown = True

    def _set(self, state: str) -> None:
        if self._cdp is None:
            return
        try:
            window = self._cdp.send("Browser.getWindowForTarget")
            self._cdp.send(
                "Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": state}}
            )
        except Exception as exc:
            log.info("Couldn't make the Chrome window %s: %s", state, exc)


def fetch_balance(
    provider: Provider,
    credentials: dict[str, str],
    profile: Path,
    *,
    with_person: bool = False,
    may_ask: bool = True,
    launcher: Callable[[Path, bool], tuple[Any, Any]] = browser_launcher,
    headless: bool = False,
    while_waiting: Callable[[Any], None] | None = None,
    screenshot_to: Path | None = None,
    seed_cookies: list[dict[str, Any]] | None = None,
) -> int:
    """Sign in if needed and read the balance, in Chrome with the program's profile folder.

    with_person shows the window from the start, for when you asked to sign in. Otherwise the
    window stays minimized, and comes up only if the site wants something from you (or, with
    may_ask off, the run stops with NeedsPerson). while_waiting is called on each poll while the
    window is up (tests use it to play the person). seed_cookies are added to a new profile:
    cookies kept by older versions of the app, so the site still knows this Mac.
    """
    if not provider.supports_fetch:
        raise FetchProblem(f"Automatic fetching isn't available for {provider.name} yet.")
    assert provider.balance_url
    playwright, context = launcher(profile, headless)
    try:
        if seed_cookies:
            try:
                context.add_cookies(seed_cookies)
            except Exception as exc:
                log.info("%s: couldn't carry over the saved cookies: %s", provider.key, exc)
        page = context.pages[0] if context.pages else context.new_page()
        window = _Window(context, page, headless)
        if with_person:
            window.show()
        else:
            window.hide()
        page.goto(provider.balance_url, wait_until="domcontentloaded")
        try:
            return _sign_in_and_read(page, provider, credentials, window, may_ask, while_waiting)
        except FetchProblem:
            if screenshot_to:
                _screenshot(page, screenshot_to)
            raise
    finally:
        try:
            context.close()
        finally:
            playwright.stop()


def _scroll_on(page) -> None:
    """Scroll a screen further down the page, or back to the top once at the bottom."""
    try:
        page.evaluate(
            "() => innerHeight + scrollY >= document.documentElement.scrollHeight - 2"
            " ? scrollTo(0, 0) : scrollBy(0, innerHeight * 0.8)"
        )
    except Exception:  # the page is changing
        pass


def _screenshot(page, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        pass


def _ask_for_you(window: _Window, provider: Provider, may_ask: bool) -> float:
    """Bring the window up for you and return the new deadline, or stop if that's not allowed."""
    if not may_ask:
        raise NeedsPerson(f"{provider.name} wants to confirm it's you. Click Sign in to enter the code.")
    log.info("%s: the site needs you, bringing the window up", provider.key)
    window.show()
    return time.monotonic() + PERSON_TIMEOUT


def _sign_in_and_read(page, provider: Provider, credentials, window: _Window, may_ask: bool, while_waiting) -> int:
    assert provider.balance_url
    started = time.monotonic()
    deadline = started + (PERSON_TIMEOUT if window.shown else QUIET_TIMEOUT)
    filled_username = filled_password = False
    submitted_at: float | None = None
    last_visit = started
    last_where = last_seen = ""
    reading: int | None = None
    read_at = scrolled_at = 0.0
    # When the run reached the balance page and started looking for the number.
    looking_since: float | None = None

    while True:
        now = time.monotonic()
        if now >= deadline:
            if window.shown:
                raise NeedsPerson(f"The {provider.name} window timed out before the sign-in finished. Try again.")
            deadline = _ask_for_you(window, provider, may_ask)
            continue
        if (where := _where(page.url)) != last_where:
            log.info("%s: at %s", provider.key, where)
            last_where = where
        frame, username, password = _login_fields(page)
        on_site = _same_site(page.url, provider.balance_url)
        at_balance_page = _at_balance_page(page.url, provider.balance_url)
        if not at_balance_page:
            looking_since = None

        if password is not None:
            if not filled_password:
                if username is not None and not username.input_value():
                    username.fill(credentials.get("username", ""))
                password.fill(credentials.get("password", ""))
                password.press("Enter")
                log.info("%s: submitted the login", provider.key)
                filled_username = filled_password = True
                submitted_at = time.monotonic()
                time.sleep(POLL * 2)
                continue
            # The sign-in form is back after we submitted: wrong login, or a site hiccup.
            if _REJECTED_WORDS.search(_page_text(page)):
                log.info("%s: the site rejected the login", provider.key)
                raise LoginRejected(f"{provider.name} didn't accept the saved username or password. Save it again.")
        else:
            if at_balance_page or (on_site and not _looks_like_sign_in(page.url)):
                balance, seen = read_balance(page, provider)
                if seen != last_seen:
                    log.info("%s: %s", provider.key, seen)
                    last_seen = seen
                if balance is not None:
                    if balance == reading and time.monotonic() - read_at >= STEADY:
                        log.info("%s: found the balance", provider.key)
                        return balance
                    if balance != reading:
                        reading, read_at = balance, time.monotonic()
                    time.sleep(POLL)
                    continue
            if at_balance_page:
                looking_since = looking_since or time.monotonic()
                looked = time.monotonic() - looking_since
                if looked > TROUBLE_GRACE and (trouble := _site_trouble(page)):
                    log.info("%s: the site shows an error", provider.key)
                    raise FetchProblem(f"{provider.name} says: “{trouble}” Try again later.")
                if looked > READ_TIMEOUT:
                    raise FetchProblem(
                        f"Signed in to {provider.name}, but couldn't find your {provider.unit} on the page. "
                        "The site may have changed; a screenshot was saved for checking."
                    )
                if looked > SCROLL_EVERY and time.monotonic() - scrolled_at > SCROLL_EVERY:
                    scrolled_at = time.monotonic()
                    _scroll_on(page)
            if username is not None and not filled_username and _looks_like_sign_in(page.url):
                # Sites that ask for the username first and the password on the next screen.
                username.fill(credentials.get("username", ""))
                username.press("Enter")
                log.info("%s: submitted the username", provider.key)
                filled_username = True
                time.sleep(POLL * 2)
                continue
            if username is None and not on_site and time.monotonic() - last_visit > 8:
                # Signed in, but the site landed somewhere else: go to the balance page. (A page with
                # a box to type in, like a security code, is left alone.)
                last_visit = time.monotonic()
                log.info("%s: going to the balance page", provider.key)
                try:
                    page.goto(provider.balance_url, wait_until="domcontentloaded")
                except Exception as exc:
                    log.info("%s: couldn't open the balance page: %s", provider.key, exc)
                continue

        # Long after the login went in and still not on the balance page: the site wants a code.
        if (
            not window.shown
            and not at_balance_page
            and submitted_at
            and time.monotonic() - submitted_at > CHALLENGE_GRACE
        ):
            deadline = _ask_for_you(window, provider, may_ask)
        if window.shown and while_waiting:
            while_waiting(page)
        time.sleep(POLL)
