"""Signs in to a program's website in Chrome and reads the balance, like you would by hand.

Each program has its own Chrome profile in the app's data folder, used for every run, so the site
sees the same browser every time and remembers it the way your own Chrome is remembered: after
the first sign-in it usually skips the security code. A refresh runs in a window off screen and
types the saved login itself, on whichever page the site shows it. Only when the site asks for
something only you can give, like a code texted to your phone, does the window come up, and the
app says why.
"""

import json
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

# How long a window that's up for you waits for you to finish.
PERSON_TIMEOUT = 5 * 60
# How long a refresh tries out of sight before bringing its window up for you.
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
# How many times the login is typed in one run: once, plus once more if the site cleared it
# without saying it was wrong (some pages reset their form while they finish loading). Never
# more, so a wrong password can't lock the account.
LOGIN_TRIES = 2
# How long after typing the login an empty box counts as cleared by the site.
RETRY_AFTER = 3
# How long after pressing Enter on a username the run clicks the form's Continue button instead.
NUDGE_AFTER = 3
# How long after the login went in a "confirm it's you" page is trusted to be what's showing.
SETTLE = 2
WINDOW_SIZE = (1200, 900)
# Where the window sits. A refresh works off every screen, out of sight but still loading pages
# like any open window. When it needs you, it moves on screen.
HIDDEN_POSITION = (-10000, 60)
SHOWN_POSITION = (80, 60)

# Describes each visible box you can type in, for picking the username and password boxes: its
# type, and the words that say what it's for (its label, placeholder, name and so on).
_FIELDS = r"""
(inputs) => inputs.map((input, index) => {
  const box = input.getBoundingClientRect();
  if (!box.width || !box.height || getComputedStyle(input).visibility === "hidden") return null;
  if (input.disabled || input.readOnly) return null;
  const words = [input.name, input.id, input.getAttribute("autocomplete"), input.placeholder,
                 input.getAttribute("aria-label")];
  for (const label of input.labels || []) words.push(label.innerText);
  const root = input.getRootNode();
  for (const id of (input.getAttribute("aria-labelledby") || "").split(/\s+/)) {
    const named = id && ((root.getElementById && root.getElementById(id)) || document.getElementById(id));
    if (named) words.push(named.innerText);
  }
  // Whether the box sits with words about signing in, like United's "Sign in for the best
  // experience" card, and not, say, a newsletter's "Sign up for emails" box.
  let signIn = false;
  const up = (node) => node.parentElement || node.getRootNode().host;
  for (let box = up(input), depth = 0; box && depth < 8; box = up(box), depth++) {
    const text = box.innerText || "";
    if (text.length > 2000) break;
    if (/\b(?:sign|log)\s*(?:in|on)\b|\blogin\b/i.test(text)) { signIn = true; break; }
  }
  return {
    index,
    signIn,
    type: (input.getAttribute("type") || "text").toLowerCase(),
    autocomplete: (input.getAttribute("autocomplete") || "").toLowerCase(),
    about: words.filter(Boolean).join(" ").replace(/\s+/g, " ").toLowerCase(),
  };
}).filter(Boolean)
"""
# The page's visible text, including what's drawn inside web components (which a page's plain text
# leaves out), with a line break around each block, like you'd read it.
_DEEP_TEXT = r"""
() => {
  const skip = new Set(["head", "script", "style", "noscript", "template", "svg"]);
  const childrenOf = (node) => {
    if (node.shadowRoot) return node.shadowRoot.childNodes;
    if (node.localName === "slot") {
      const assigned = node.assignedNodes({ flatten: true });
      if (assigned.length) return assigned;
    }
    return node.childNodes;
  };
  const visit = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return node.data;
    if (node.nodeType !== Node.ELEMENT_NODE || skip.has(node.localName)) return "";
    if (node.localName === "br") return "\n";
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return "";
    let joined = "";
    for (const child of childrenOf(node)) joined += visit(child);
    const inline = style.display.startsWith("inline") || style.display === "contents";
    return inline ? joined : `\n${joined}\n`;
  };
  return document.body ? visit(document.body) : "";
}
"""
# Clicks the button that sends a username box's form, like United's "Continue": the nearest one
# around the box, so a Sign in button in the page's header doesn't count.
_FORM_BUTTON = r"""
(field) => {
  const words = /^\s*(continue|next|sign\s*in|log\s*in|log\s*on|submit)\s*$/i;
  const deep = (root) => {
    const found = [...root.querySelectorAll("button, input[type=submit], input[type=button], [role=button]")];
    for (const element of root.querySelectorAll("*")) if (element.shadowRoot) found.push(...deep(element.shadowRoot));
    return found;
  };
  // The box around an element, stepping out of a web component to the element that holds it.
  const up = (node) => node.parentElement || node.getRootNode().host;
  for (let box = up(field); box; box = up(box)) {
    for (const button of deep(box)) {
      const name = button.innerText || button.value || button.getAttribute("aria-label") || "";
      if (words.test(name) && !button.disabled && button.getClientRects().length) return button;
    }
  }
  return null;
}
"""
_TEXT_TYPES = {"text", "email", "tel"}
_SEARCH_WORDS = re.compile(r"search|\bquery\b|\bq\b", re.IGNORECASE)
_CODE_WORDS = re.compile(r"code|otp|one.?time|passcode|verif|\bpin\b", re.IGNORECASE)
_USERNAME_WORDS = re.compile(r"user|e-?mail|log ?in|logon|sign ?in|member|mileage|customer id|online id", re.IGNORECASE)
# A site asking to confirm it's really you, usually with a code sent to your phone or email: what
# a site does the first time it sees a browser, and something only you can finish.
_CONFIRM_ITS_YOU = re.compile(
    r"make sure it.s (?:really )?you|(?:confirm|verify) (?:your identity|it.s (?:really )?you)"
    r"|(?:don.t|do not) recognize (?:this|your) (?:device|computer|browser)"
    r"|(?:one[- ]time|verification|temporary) (?:pass)?code|(?:enter|send|sent|get) (?:you |me )?(?:the|a) code",
    re.IGNORECASE,
)
# A site saying the login is wrong, worded either way round: "invalid username or password", or
# "the username or password you entered is incorrect". ("We don't recognize this device" is not
# about the login: that's a site asking to confirm it's you.)
_REJECTED_WORDS = re.compile(
    r"(?:incorrect|isn.t right|is not right|doesn.t match|invalid|wrong|can.t find|couldn.t find|not recognized"
    r"|(?:don.t|do not) recognize(?! (?:this|your) (?:device|computer|browser)))"
    r".{0,40}(?:password|username|user ?id|user ?name|credentials|login)"
    r"|(?:password|username|user ?id|user ?name|credentials|combination|(?:information|details) you entered)"
    r".{0,40}(?:incorrect|isn.t right|is not right|doesn.t match|don.t match|invalid|wrong|not valid|not recognized)",
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


def browser_launcher(profile: Path, headless: bool, hidden: bool = False):
    """Opens Chrome with the program's own profile: your installed Google Chrome, or
    AW_BROWSER_PATH in tests. Returns Playwright and the browser context."""
    from playwright.sync_api import Error, sync_playwright

    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    quiet_profile(profile)
    playwright = sync_playwright().start()
    width, height = WINDOW_SIZE
    left, top = HIDDEN_POSITION if hidden else SHOWN_POSITION
    options: dict[str, Any] = {
        "headless": headless,
        # Look like a normal Chrome, not one driven by a program, and keep the cookies encrypted
        # with the Mac's Keychain like your own Chrome does (Playwright would use a fake one).
        "ignore_default_args": ["--enable-automation", "--use-mock-keychain"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            f"--window-size={width},{height}",
            f"--window-position={left},{top}",
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


def quiet_profile(profile: Path) -> None:
    """Turn off Chrome's own prompts in a program's profile: its offer to save the password (the
    app keeps it, encrypted) and its "restore pages?" after a run was cut short, like when the app
    quits mid-refresh. Chrome reads these settings when it starts."""
    preferences = profile / "Default" / "Preferences"
    try:
        settings = json.loads(preferences.read_text(encoding="utf-8")) if preferences.exists() else {}
    except (OSError, ValueError):
        return  # leave a file we can't read to Chrome
    if not isinstance(settings, dict) or not isinstance(settings.setdefault("profile", {}), dict):
        return
    settings["credentials_enable_service"] = False
    settings["profile"].update(password_manager_enabled=False, exit_type="Normal", exited_cleanly=True)
    try:
        preferences.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        draft = preferences.with_name("Preferences.award-wallet")
        draft.write_text(json.dumps(settings), encoding="utf-8")
        draft.replace(preferences)
    except OSError as exc:
        log.info("Couldn't turn off Chrome's prompts: %s", exc)


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


def _frames(page):
    return [page.main_frame, *[frame for frame in page.frames if frame is not page.main_frame]]


@dataclass
class _Fields:
    """The login boxes showing on the page, in whichever frame holds them."""

    username: Any = None
    password: Any = None
    # Some other box to type in is showing, like one for a security code.
    typing: bool = False


def _username_rank(field: dict[str, str]) -> int | None:
    """How sure we are that a box wants the username: 0 is certain, 3 is any text box. None for
    boxes that are something else, like a search box or one for a code."""
    if field["type"] not in _TEXT_TYPES or _SEARCH_WORDS.search(field["about"]) or _CODE_WORDS.search(field["about"]):
        return None
    if field["autocomplete"] == "username":
        return 0
    if field["type"] == "email":
        return 1
    if _USERNAME_WORDS.search(field["about"]):
        return 2
    return 3


def _fields(page, sign_in_page: bool) -> _Fields:
    """The visible login boxes. A box counts as the username when it says so (by its label, like
    United's "Email or MileagePlus number" on its account page), or, for any text box, when it sits
    next to a password box or on a sign-in page. Search boxes never count."""
    found = _Fields()
    for frame in _frames(page):
        boxes = frame.locator("input")
        try:
            described = boxes.evaluate_all(_FIELDS)
        except Exception:  # frames come and go while a page loads
            continue
        password = next((field for field in described if field["type"] == "password"), None)
        ranked = sorted((rank, field["index"]) for field in described if (rank := _username_rank(field)) is not None)
        # Next to a password box or on a sign-in page, any text box is the username. Elsewhere, only
        # one that says it wants a username or email and sits with words about signing in.
        trusted = password or sign_in_page
        by_index = {field["index"]: field for field in described}
        username = next((index for rank, index in ranked if trusted or (rank <= 2 and by_index[index]["signIn"])), None)
        found.typing = found.typing or any(
            field["type"] in {*_TEXT_TYPES, "number"} and not _SEARCH_WORDS.search(field["about"])
            for field in described
        )
        if found.password is None and found.username is None and (password or username is not None):
            found.password = boxes.nth(password["index"]) if password else None
            found.username = boxes.nth(username) if username is not None else None
    return found


def _empty(field) -> bool:
    try:
        return not field.input_value(timeout=2000)
    except Exception:  # gone from the page: nothing to fill
        return False


def _click_form_button(field) -> bool:
    """Click the Continue (or Sign in) button of the form a username box is in."""
    try:
        button = field.evaluate_handle(_FORM_BUTTON).as_element()
        if button is None:
            return False
        button.click(timeout=3000)
        return True
    except Exception:
        return False


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
    if match := _SITE_TROUBLE.search(_deep_text(page)):
        return " ".join(match.group(0).split())[:200]
    return None


def _deep_text(page) -> str:
    """The visible text of the page and its frames, including inside web components."""
    parts = []
    for frame in _frames(page):
        try:
            parts.append(frame.evaluate(_DEEP_TEXT))
        except Exception:  # frames come and go while a page loads
            continue
    return "\n".join(parts)


def _asks_who_you_are(page) -> bool:
    """Whether the page asks to confirm it's you, like Chase's "Let's make sure it's you"."""
    return bool(_CONFIRM_ITS_YOU.search(_deep_text(page)))


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
    """The run's Chrome window: off screen while a refresh works quietly, brought on screen when
    you're needed. In tests there's no window (headless), and only the state is kept."""

    def __init__(self, context, page, headless: bool):
        self._context, self._page, self._headless = context, page, headless
        self.shown = False

    def hide(self) -> None:
        self.shown = False
        landed = self._set_bounds({"left": HIDDEN_POSITION[0], "top": HIDDEN_POSITION[1]})
        if landed and landed.get("left", 0) + landed.get("width", 0) > 0:
            # The Mac kept the window on screen: put it in the Dock instead.
            log.info("The Chrome window can't sit off screen here, so it's minimized instead")
            self._set_bounds({"windowState": "minimized"})

    def show(self) -> None:
        self.shown = True
        self._set_bounds({"left": SHOWN_POSITION[0], "top": SHOWN_POSITION[1]})
        try:
            self._page.bring_to_front()
        except Exception:
            pass

    def _set_bounds(self, bounds: dict[str, Any]) -> dict[str, Any] | None:
        """Move or minimize the window, and return where it ended up. Each change gets its own
        connection to Chrome: a connection can end when a site moves the page to another process."""
        if self._headless:
            return None
        try:
            cdp = self._context.new_cdp_session(self._page)
        except Exception as exc:
            log.info("Can't control the Chrome window: %s", exc)
            return None
        try:
            window = cdp.send("Browser.getWindowForTarget")
            window_id = window["windowId"]
            if "left" in bounds and window["bounds"].get("windowState", "normal") != "normal":
                # A minimized window has to be restored before it can move.
                cdp.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": bounds})
            landed = cdp.send("Browser.getWindowForTarget")["bounds"]
            if "left" in bounds and (landed.get("left"), landed.get("top")) != (bounds["left"], bounds["top"]):
                log.info(
                    "The Chrome window went to %s,%s instead of %s,%s",
                    landed.get("left"),
                    landed.get("top"),
                    bounds["left"],
                    bounds["top"],
                )
            return landed
        except Exception as exc:
            log.info("Couldn't move the Chrome window: %s", exc)
            return None
        finally:
            try:
                cdp.detach()
            except Exception:
                pass


def fetch_balance(
    provider: Provider,
    credentials: dict[str, str],
    profile: Path,
    *,
    with_person: bool = False,
    may_ask: bool = True,
    launcher: Callable[[Path, bool, bool], tuple[Any, Any]] = browser_launcher,
    headless: bool = False,
    while_waiting: Callable[[Any], None] | None = None,
    screenshot_to: Path | None = None,
    seed_cookies: list[dict[str, Any]] | None = None,
    on_needs_you: Callable[[str], None] | None = None,
) -> int:
    """Sign in if needed and read the balance, in Chrome with the program's profile folder.

    with_person shows the window from the start, for when you asked to sign in. Otherwise the
    window works off screen, and comes on screen only if the site wants something from you (or,
    with may_ask off, the run stops with NeedsPerson); on_needs_you then gets a note saying what to
    do, for the app to show. while_waiting is called on each poll while the window is up (tests use
    it to play the person). seed_cookies are added to a new profile: cookies kept by older versions
    of the app, so the site still knows this Mac.
    """
    if not provider.supports_fetch:
        raise FetchProblem(f"Automatic fetching isn't available for {provider.name} yet.")
    assert provider.balance_url
    playwright, context = launcher(profile, headless, not with_person)
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

        def ask_for_you(note: str) -> float:
            """Bring the window up for you and return the new deadline, or stop if that's not allowed."""
            if not may_ask:
                raise NeedsPerson(f"{provider.name} wants to confirm it's you. Click Sign in to enter the code.")
            log.info("%s: the site needs you, bringing the window up (the page: %s)", provider.key, _title(page))
            if screenshot_to:
                _screenshot(page, screenshot_to.with_name(f"{screenshot_to.stem}-needs-you.png"))
            window.show()
            if on_needs_you:
                on_needs_you(note)
            return time.monotonic() + PERSON_TIMEOUT

        page.goto(provider.balance_url, wait_until="domcontentloaded")
        try:
            return _sign_in_and_read(page, provider, credentials, window, ask_for_you, while_waiting)
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


def _title(page) -> str:
    try:
        return " ".join(page.title().split())[:80]
    except Exception:
        return ""


def _confirm_note(provider: Provider) -> str:
    return (
        f"{provider.name} wants to confirm it's you, usually only the first time. Finish it in the "
        f"{provider.name} window; after that, refreshes run on their own."
    )


def _finish_note(provider: Provider) -> str:
    return f"{provider.name} needs you to finish signing in, in its Chrome window."


def _sentences(text: str) -> set[str]:
    """The lines of a page's text that say something (three words or more)."""
    return {" ".join(line.split()) for line in text.splitlines() if len(line.split()) >= 3}


def _type_login(fields: _Fields, credentials: dict[str, str]) -> bool:
    """Type the username (unless the site kept it) and password, and send them."""
    try:
        if fields.username is not None and _empty(fields.username):
            fields.username.fill(credentials.get("username", ""))
        fields.password.fill(credentials.get("password", ""))
        fields.password.press("Enter")
        return True
    except Exception as exc:  # the form changed under us: try again on the next look
        log.info("Couldn't type the login: %s", type(exc).__name__)
        return False


def _type_username(fields: _Fields, credentials: dict[str, str]) -> bool:
    try:
        fields.username.fill(credentials.get("username", ""))
        fields.username.press("Enter")
        return True
    except Exception as exc:
        log.info("Couldn't type the username: %s", type(exc).__name__)
        return False


def _sign_in_and_read(
    page, provider: Provider, credentials, window: _Window, ask_for_you: Callable[[str], float], while_waiting
) -> int:
    assert provider.balance_url
    started = time.monotonic()
    deadline = started + (PERSON_TIMEOUT if window.shown else QUIET_TIMEOUT)
    username_tries = login_tries = 0
    # When the username, and the whole login, last went in.
    username_at = submitted_at = 0.0
    # What the sign-in page said before the login went in.
    form_said: set[str] = set()
    nudged = False
    last_visit = started
    last_where = last_seen = ""
    reading: int | None = None
    read_at = scrolled_at = 0.0
    # When the run reached the balance page and started looking for the number.
    looking_since: float | None = None

    while True:
        now = time.monotonic()
        if page.is_closed():
            raise NeedsPerson(f"The {provider.name} window was closed before the sign-in finished. Try again.")
        if now >= deadline:
            if window.shown:
                raise NeedsPerson(f"The {provider.name} window timed out before the sign-in finished. Try again.")
            deadline = ask_for_you(_finish_note(provider))
            continue
        url = page.url
        if (where := _where(url)) != last_where:
            log.info("%s: at %s", provider.key, where)
            last_where = where
        on_site = _same_site(url, provider.balance_url)
        sign_in_page = _looks_like_sign_in(url)
        at_balance_page = _at_balance_page(url, provider.balance_url)
        if not at_balance_page:
            looking_since = None
        fields = _fields(page, sign_in_page)

        if fields.password is not None:
            if login_tries and _REJECTED_WORDS.search(_deep_text(page)):
                log.info("%s: the site rejected the login", provider.key)
                raise LoginRejected(f"{provider.name} didn't accept the saved username or password. Save it again.")
            # The form is back, empty, and the page says nothing new (no "try again", no error): the
            # site reset it, as some do while they finish loading. Anything else is left to you.
            cleared = (
                login_tries < LOGIN_TRIES
                and now - submitted_at > RETRY_AFTER
                and _empty(fields.password)
                and not _sentences(_deep_text(page)) - form_said
            )
            if not login_tries or cleared:
                if login_tries:
                    log.info("%s: the site cleared the login without saying why; typing it again", provider.key)
                else:
                    form_said = _sentences(_deep_text(page))
                if _type_login(fields, credentials):
                    log.info("%s: submitted the login", provider.key)
                    login_tries += 1
                    submitted_at = time.monotonic()
                time.sleep(POLL * 2)
                continue
        else:
            if at_balance_page or (on_site and not sign_in_page):
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
            # The site asks to confirm it's you, like Chase's "Let's make sure it's you" (on its
            # dashboard's own address). Only you can do that, so the window comes up right away.
            if (
                not window.shown
                and reading is None
                and (login_tries or username_tries)
                and time.monotonic() - max(submitted_at, username_at) > SETTLE
                and _asks_who_you_are(page)
            ):
                log.info("%s: the site asks to confirm it's you", provider.key)
                deadline = ask_for_you(_confirm_note(provider))
                continue
            if at_balance_page:
                looking_since = looking_since or time.monotonic()
                looked = time.monotonic() - looking_since
                if looked > TROUBLE_GRACE and (trouble := _site_trouble(page)):
                    log.info("%s: the site shows an error", provider.key)
                    raise FetchProblem(f"{provider.name} says: “{trouble}” Try again later.")
                if looked > READ_TIMEOUT and not window.shown:
                    if _asks_who_you_are(page):
                        log.info("%s: the site asks to confirm it's you", provider.key)
                        deadline = ask_for_you(_confirm_note(provider))
                        continue
                    raise FetchProblem(
                        f"Couldn't find your {provider.unit} on {provider.name}'s page. "
                        "The site may have changed; a screenshot was saved for checking."
                    )
                if looked > SCROLL_EVERY and time.monotonic() - scrolled_at > SCROLL_EVERY:
                    scrolled_at = time.monotonic()
                    _scroll_on(page)
            if fields.username is not None:
                # Sites that ask for the username first and the password on the next screen, on a
                # sign-in page or right on the account page, like United's.
                cleared = username_tries < LOGIN_TRIES and now - username_at > RETRY_AFTER and _empty(fields.username)
                if not username_tries or cleared:
                    if _type_username(fields, credentials):
                        log.info("%s: submitted the username", provider.key)
                        username_tries += 1
                        username_at, nudged = time.monotonic(), False
                    time.sleep(POLL * 2)
                    continue
                if not nudged and now - username_at > NUDGE_AFTER:
                    # Enter didn't send it: click the form's Continue button, like you would.
                    nudged = True
                    if _click_form_button(fields.username):
                        log.info("%s: clicked the form's button", provider.key)
            if not fields.typing and not on_site and time.monotonic() - last_visit > 8:
                # Signed in, but the site landed somewhere else: go to the balance page. (A page with
                # a box to type in, like a security code, is left alone.)
                last_visit = time.monotonic()
                log.info("%s: going to the balance page", provider.key)
                try:
                    page.goto(provider.balance_url, wait_until="domcontentloaded")
                except Exception as exc:
                    log.info("%s: couldn't open the balance page: %s", provider.key, exc)
                continue

        # Long after the login went in and still not on the balance page: the site wants something.
        if (
            not window.shown
            and not at_balance_page
            and login_tries
            and time.monotonic() - submitted_at > CHALLENGE_GRACE
        ):
            deadline = ask_for_you(_finish_note(provider))
        if window.shown and while_waiting:
            while_waiting(page)
        time.sleep(POLL)
