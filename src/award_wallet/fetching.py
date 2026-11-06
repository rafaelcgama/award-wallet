"""Signs in to a program's website in Chrome and reads the balance, like you would by hand.

Each program has its own Chrome profile in the app's data folder, used for every run, so the site
sees the same browser every time and remembers it the way your own Chrome is remembered: after
the first sign-in it usually skips the security code.

Chrome always runs in its hidden mode: no window, nothing in the Dock. A refresh types the saved
login itself, a key at a time like a person, on whichever page the site shows it. When the site
wants something only you can give, like a code texted to your phone, the refresh stops and the
app says so; nothing pops up. When you click Sign in, the same hidden Chrome signs in and the app
shows its page in Award Wallet's own window (see sign_in_view), where you finish what the site
asks. Sites that tell a Chrome window from hidden Chrome then know the browser that refreshes,
not a window it never uses. If the site turned the saved login down and you signed in with
another, the app keeps the one that worked.
"""

import base64
import json
import logging
import os
import platform
import plistlib
import random
import re
import secrets
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from award_wallet.providers import Provider
from award_wallet.sign_in_view import SignInView

log = logging.getLogger(__name__)

# How long a sign-in you opened waits for you, counted from your last click or key.
PERSON_TIMEOUT = 5 * 60
# How long a refresh tries before it stops and says the site needs you.
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
# How long a sign-in form shows before the login goes in: the page's own scripts finish setting it
# up, and a person takes at least that long. Typed right away, Capital One turned the login down.
FORM_SETTLE = 1.5
# The pause between keys while typing a login, and before sending it, in seconds.
KEY_PAUSE = (0.05, 0.16)
SEND_PAUSE = (0.3, 0.7)
# Chrome's window, out of sight. Wider than tall, so the page fits the app's window as you sign in.
WINDOW_SIZE = (1200, 760)
# The largest picture of the page sent to the app's window while you sign in, in pixels, and its
# JPEG quality.
PICTURE_SIZE = (2000, 1400)
PICTURE_QUALITY = 72
# While you sign in, how often your clicks and keys go to the page, in seconds.
INPUT_EVERY = 0.05
# Google Chrome, whose version says what Chrome's hidden mode should tell sites it is.
CHROME_APP = Path("/Applications/Google Chrome.app")

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
    r"|(?:don.t|do not|didn.t|did not) recognize(?! (?:this|your) (?:device|computer|browser)))"
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

  // Text only screen readers get, squeezed into a 1-pixel box, like ", more about your points".
  const forScreenReaders = (style) =>
    style.position === "absolute" && style.overflow === "hidden" &&
    parseFloat(style.width) <= 1 && parseFloat(style.height) <= 1;

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
    if (style.display === "none" || style.visibility === "hidden" || forScreenReaders(style)) return "";
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


def browser_launcher(profile: Path):
    """Opens Chrome with the program's own profile, in Chrome's hidden mode: no window and nothing
    in the Dock. It's your installed Google Chrome, or AW_BROWSER_PATH in tests. Returns
    Playwright and the browser context."""
    from playwright.sync_api import Error, sync_playwright

    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    quiet_profile(profile)
    playwright = sync_playwright().start()
    try:
        options = _launch_options()
        context = _launch(playwright, profile, options, Error)
        if options.get("user_agent") is None:
            # Chrome's hidden mode calls itself "HeadlessChrome", which some sites turn away. Tell
            # them what its window would say. (Normally Chrome's version gives that up front; this
            # second start is for a Chrome found some other way.)
            seen = _user_agent(context)
            if "HeadlessChrome/" in seen:
                context.close()
                options["user_agent"] = seen.replace("HeadlessChrome/", "Chrome/")
                context = _launch(playwright, profile, options, Error)
        _describe_this_mac(context, options.get("user_agent"))
    except BaseException:
        playwright.stop()
        raise
    return playwright, context


def _launch_options() -> dict[str, Any]:
    width, height = WINDOW_SIZE
    args = ["--disable-blink-features=AutomationControlled", "--disk-cache-size=52428800"]
    options: dict[str, Any] = {
        "headless": True,
        # Look like a normal Chrome, not one driven by a program, and keep the cookies encrypted
        # with the Mac's Keychain like your own Chrome does (Playwright would use a fake one).
        "ignore_default_args": ["--enable-automation", "--use-mock-keychain"],
        "args": args,
        # The page fills the window, like any Chrome window.
        "no_viewport": True,
        # Nothing a site offers for download is saved.
        "accept_downloads": False,
    }
    # The same screen and browser a site sees in a window on this Mac.
    if screen := mac_screen():
        screen_width, screen_height, scale = screen
        width, height = min(width, screen_width), min(height, screen_height - 60)
        args.append(f"--screen-info={{0,0 {screen_width * scale}x{screen_height * scale} devicePixelRatio={scale}}}")
    args.append(f"--window-size={width},{height}")
    options["user_agent"] = chrome_user_agent()
    if path := os.environ.get("AW_BROWSER_PATH"):
        options["executable_path"] = path
    else:
        options["channel"] = "chrome"
    return options


def _launch(playwright, profile: Path, options: dict[str, Any], error: type[Exception]):
    try:
        return playwright.chromium.launch_persistent_context(str(profile), **options)
    except error as exc:
        message = str(exc).lower()
        if "chrome" in message and ("not found" in message or "doesn't exist" in message):
            raise ChromeMissing(
                "Award Wallet signs in through Google Chrome, which isn't installed. "
                "Get it at google.com/chrome, then refresh."
            ) from None
        raise


def _user_agent(context) -> str:
    try:
        page = context.pages[0] if context.pages else context.new_page()
        return str(page.evaluate("navigator.userAgent"))
    except Exception:
        return ""


def chrome_user_agent() -> str | None:
    """What Google Chrome on this Mac tells sites from a window, worked out from its version (Chrome
    only gives sites the first number of it, like "Chrome/153.0.0.0"). None away from a Mac's
    Google Chrome."""
    if sys.platform != "darwin" or os.environ.get("AW_BROWSER_PATH"):
        return None
    try:
        with (CHROME_APP / "Contents" / "Info.plist").open("rb") as file:
            version = str(plistlib.load(file).get("CFBundleShortVersionString", ""))
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    major = version.split(".")[0]
    if not major.isdigit():
        return None
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


def mac_screen() -> tuple[int, int, int] | None:
    """The Mac's main screen: its width and height in points, and how many pixels make a point
    (2 on a Retina screen). None elsewhere, or if macOS doesn't say."""
    if sys.platform != "darwin":
        return None
    try:
        import Quartz

        mode = Quartz.CGDisplayCopyDisplayMode(Quartz.CGMainDisplayID())
        width, height = int(Quartz.CGDisplayModeGetWidth(mode)), int(Quartz.CGDisplayModeGetHeight(mode))
        pixels = int(Quartz.CGDisplayModeGetPixelWidth(mode))
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height, max(1, round(pixels / width))


def _client_hints() -> dict[str, Any] | None:
    """The details about this Mac Chrome gives sites that ask (macOS version, Apple or Intel chip).
    Playwright guesses them from the user agent, which says "Intel Mac OS X 10_15_7" on every Mac."""
    if sys.platform != "darwin":
        return None
    numbers = (platform.mac_ver()[0].split(".") + ["0", "0"])[:3]
    return {
        "platform": "macOS",
        "platformVersion": ".".join(number or "0" for number in numbers),
        "architecture": "arm" if platform.machine() == "arm64" else "x86",
        "bitness": "64",
        "model": "",
        "mobile": False,
        "wow64": False,
    }


def _describe_this_mac(context, user_agent: str | None) -> None:
    """Give each page of the hidden Chrome the same details about this Mac that a window gives."""
    hints = _client_hints()
    if not (hints and user_agent):
        return
    # An override lasts while its connection to Chrome does, so the connections are kept.
    kept: list[Any] = []

    def describe(page) -> None:
        try:
            connection = context.new_cdp_session(page)
            connection.send("Emulation.setUserAgentOverride", {"userAgent": user_agent, "userAgentMetadata": hints})
            kept.append(connection)
        except Exception as exc:
            log.info("Couldn't give the page this Mac's details: %s", type(exc).__name__)

    for page in context.pages:
        describe(page)
    context.on("page", describe)


def quiet_profile(profile: Path) -> None:
    """Turn off Chrome's own prompts in a program's profile: its offer to save the password (the
    app keeps it, encrypted) and its "restore pages?" after a run was cut short, like when the app
    quits mid-refresh. Chrome also stops remembering what's typed into forms, like the username.
    Chrome reads these settings when it starts."""
    preferences = profile / "Default" / "Preferences"
    try:
        settings = json.loads(preferences.read_text(encoding="utf-8")) if preferences.exists() else {}
    except (OSError, ValueError):
        return  # leave a file we can't read to Chrome
    if not isinstance(settings, dict) or not isinstance(settings.setdefault("profile", {}), dict):
        return
    settings["credentials_enable_service"] = False
    settings["profile"].update(password_manager_enabled=False, exit_type="Normal", exited_cleanly=True)
    if isinstance(autofill := settings.setdefault("autofill", {}), dict):
        autofill.update(enabled=False, profile_enabled=False, credit_card_enabled=False)
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


# Runs in each page while you sign in: passes on what goes into login boxes, so a login you fix by
# hand can be kept. It reports through a hook the page itself can't see.
_WATCH_TYPING = r"""
(name) => {
  const send = globalThis[name];
  try { delete globalThis[name]; } catch (error) {}
  if (typeof send !== "function") return;
  const note = (event) => {
    // Only what you type: the page's own scripts can't make up a login to be kept.
    if (!event.isTrusted) return;
    const input = event.composedPath ? event.composedPath()[0] : event.target;
    if (!(input instanceof HTMLInputElement)) return;
    const type = (input.getAttribute("type") || "text").toLowerCase();
    if (!["text", "email", "tel", "password"].includes(type)) return;
    const words = [input.name, input.id, input.getAttribute("autocomplete"), input.placeholder,
                   input.getAttribute("aria-label")];
    for (const label of input.labels || []) words.push(label.innerText);
    send(JSON.stringify({
      type,
      autocomplete: (input.getAttribute("autocomplete") || "").toLowerCase(),
      about: words.filter(Boolean).join(" ").replace(/\s+/g, " ").toLowerCase(),
      value: input.value,
    }));
  };
  addEventListener("input", note, true);
  addEventListener("change", note, true);
}
"""


class _TypingWatcher:
    """Notes what goes into the login boxes while you sign in (only ever kept, encrypted, never
    logged), so a login that worked can replace a saved one the site turned down."""

    def __init__(self, context, page):
        self.username: str | None = None
        self.password: str | None = None
        self._name = "_" + secrets.token_hex(6)
        try:
            connection = context.new_cdp_session(page)
            connection.on("Runtime.bindingCalled", self._typed)
            connection.send("Page.enable")
            connection.send("Runtime.enable")
            connection.send("Runtime.addBinding", {"name": self._name})
            source = f"({_WATCH_TYPING})({json.dumps(self._name)})"
            connection.send("Page.addScriptToEvaluateOnNewDocument", {"source": source})
            self._connection = connection
        except Exception as exc:
            log.info("Can't follow the login boxes: %s", type(exc).__name__)

    def _typed(self, event: dict[str, Any]) -> None:
        if event.get("name") != self._name:
            return
        try:
            field = json.loads(event["payload"])
            value = str(field["value"])
        except (KeyError, TypeError, ValueError):
            return
        if _CODE_WORDS.search(field.get("about", "")) or _SEARCH_WORDS.search(field.get("about", "")):
            return  # a security code or a search, not the login
        if field.get("type") == "password":
            self.password = value
        elif (rank := _username_rank(field)) is not None and rank <= 2:
            self.username = value.strip()

    def login(self, saved: dict[str, str]) -> dict[str, str] | None:
        """The login you typed, if it differs from the saved one."""
        if not self.password:
            return None
        typed = {"password": self.password}
        if self.username:
            typed["username"] = self.username
        if all(saved.get(name) == value for name, value in typed.items()):
            return None
        return typed


def fetch_balance(
    provider: Provider,
    credentials: dict[str, str],
    profile: Path,
    *,
    view: SignInView | None = None,
    type_login: bool = True,
    launcher: Callable[[Path], tuple[Any, Any]] = browser_launcher,
    while_waiting: Callable[[Any], None] | None = None,
    screenshot_to: Path | None = None,
    seed_cookies: list[dict[str, Any]] | None = None,
    on_new_login: Callable[[dict[str, str]], None] | None = None,
) -> int:
    """Sign in if needed and read the balance, in hidden Chrome with the program's profile folder.

    A refresh (no view) never shows anything: if the site wants something only you can give, it
    stops with NeedsPerson, whose message says to click Sign in. Sign in runs the same Chrome with a
    view: its page shows in the app's window and your clicks and keys go to it. The app types the
    saved login (unless type_login is off, when the site already turned it down) and the view says
    what the site wants from you. If the site turned the saved login down and you signed in with
    another, on_new_login gets the one that worked.

    while_waiting is called on each look at the page while you sign in (tests use it to play you).
    seed_cookies are added to a new profile: cookies kept by older versions of the app, so the site
    still knows this Mac.
    """
    if not provider.supports_fetch:
        raise FetchProblem(f"Automatic fetching isn't available for {provider.name} yet.")
    assert provider.balance_url
    playwright, context = launcher(profile)
    try:
        if seed_cookies:
            try:
                context.add_cookies(seed_cookies)
            except Exception as exc:
                log.info("%s: couldn't carry over the saved cookies: %s", provider.key, exc)
        page = context.pages[0] if context.pages else context.new_page()
        watcher = _TypingWatcher(context, page) if view else None
        screen = _Screen(context, page, view) if view else None
        run = _Run(provider, credentials, view, screen, type_login, while_waiting)
        if view and not type_login:
            # The site turned the saved login down on the last refresh: you sign in this time.
            run.needs_you(_rejected_note(provider), "")
        page.goto(provider.balance_url, wait_until="domcontentloaded")
        try:
            balance = _sign_in_and_read(page, run)
        except FetchProblem:
            if screenshot_to:
                _screenshot(page, screenshot_to)
            raise
        if watcher and on_new_login and (run.rejected or not type_login):
            if typed := watcher.login(credentials):
                log.info("%s: keeping the login you signed in with", provider.key)
                on_new_login(typed)
        return balance
    finally:
        try:
            context.close()
        finally:
            playwright.stop()


class _Screen:
    """Shows the hidden Chrome's page in the app's window while you sign in (see sign_in_view), and
    passes your clicks and keys on to the page, as if you made them in Chrome itself."""

    def __init__(self, context, page, view: SignInView):
        self._page, self._view = page, view
        self._connection: Any = None
        try:
            self._connection = context.new_cdp_session(page)
            self._connection.on("Page.screencastFrame", self._frame)
            width, height = PICTURE_SIZE
            self._connection.send(
                "Page.startScreencast",
                {"format": "jpeg", "quality": PICTURE_QUALITY, "maxWidth": width, "maxHeight": height},
            )
        except Exception as exc:
            log.info("Can't show the page in the window: %s", type(exc).__name__)

    def _frame(self, event: dict[str, Any]) -> None:
        # Chrome sends no more pictures until it hears this one arrived.
        try:
            metadata = event["metadata"]
            self._view.show(base64.b64decode(event["data"]), metadata["deviceWidth"], metadata["deviceHeight"])
        except Exception:
            pass
        try:
            self._connection.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        except Exception:
            pass

    def pump(self) -> set[str]:
        """Pass on the clicks and keys you made since the last call. Returns what kinds they were."""
        kinds = set()
        for event in self._view.take():
            kinds.add(event["kind"])
            try:
                self._dispatch(event)
            except Exception as exc:  # the page changed under it, like a click that missed
                log.info("Couldn't pass on a %s: %s", event["kind"], type(exc).__name__)
        return kinds

    def _dispatch(self, event: dict[str, Any]) -> None:
        mouse, keyboard = self._page.mouse, self._page.keyboard
        if event["kind"] == "click":
            mouse.click(event["x"], event["y"])
        elif event["kind"] == "scroll":
            mouse.move(event["x"], event["y"])
            mouse.wheel(event["dx"], event["dy"])
        elif event["kind"] == "text":
            keyboard.type(event["text"])
        elif event["kind"] == "key":
            keyboard.press(("Shift+" if event["shift"] else "") + event["key"])


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
    """Save what the page shows, for fixing a program's reader. Every box on it is blacked out,
    so the screenshot never shows a username, a code or anything else typed into it."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        boxes = [frame.locator("input, textarea, select") for frame in page.frames]
        page.screenshot(path=str(path), full_page=True, mask=boxes, mask_color="#000")
    except Exception:
        pass


def _title(page) -> str:
    try:
        return " ".join(page.title().split())[:80]
    except Exception:
        return ""


def _confirm_note(provider: Provider, with_you: bool) -> str:
    finish = "Do what it asks below" if with_you else "Click Sign in to do it"
    return (
        f"{provider.name} wants to confirm it's you, usually only the first time. {finish}; after that, "
        "refreshes run on their own."
    )


def _finish_note(provider: Provider, with_you: bool) -> str:
    if with_you:
        return f"{provider.name} needs you to finish signing in below."
    return f"{provider.name} needs you to finish signing in. Click Sign in."


def _rejected_note(provider: Provider) -> str:
    return f"{provider.name} didn't take the saved login. Sign in below, and Award Wallet keeps the login that works."


def _sentences(text: str) -> set[str]:
    """The lines of a page's text that say something (three words or more)."""
    return {" ".join(line.split()) for line in text.splitlines() if len(line.split()) >= 3}


def _pause(span: tuple[float, float]) -> None:
    time.sleep(random.uniform(*span))


def _type_into(field, text: str) -> None:
    """Type like a person: click into the box, then one key at a time. Some sites ignore a box
    filled in all at once: Capital One answered "We didn't recognize that info"."""
    try:
        field.click(timeout=2000)
    except Exception:  # something sits over the box, like a cookie banner: typing still reaches it
        field.focus(timeout=2000)
    if field.input_value(timeout=2000):
        field.fill("", timeout=2000)
    for character in text:
        field.press_sequentially(character, timeout=2000)
        _pause(KEY_PAUSE)
    if field.input_value(timeout=2000) != text:
        # The box changed what was typed, or lost a key: put the login in whole.
        field.fill(text, timeout=2000)


def _type_login(fields: _Fields, credentials: dict[str, str]) -> bool:
    """Type the username (unless the site kept it) and password, and send them."""
    try:
        if fields.username is not None and _empty(fields.username):
            _type_into(fields.username, credentials.get("username", ""))
        _type_into(fields.password, credentials.get("password", ""))
        _pause(SEND_PAUSE)
        fields.password.press("Enter")
        return True
    except Exception as exc:  # the form changed under us: try again on the next look
        log.info("Couldn't type the login: %s", type(exc).__name__)
        return False


def _type_username(fields: _Fields, credentials: dict[str, str]) -> bool:
    try:
        _type_into(fields.username, credentials.get("username", ""))
        _pause(SEND_PAUSE)
        fields.username.press("Enter")
        return True
    except Exception as exc:
        log.info("Couldn't type the username: %s", type(exc).__name__)
        return False


@dataclass
class _Run:
    provider: Provider
    credentials: dict[str, str]
    # Set while you sign in in the app's window. A refresh has none, and shows nothing.
    view: SignInView | None
    screen: _Screen | None
    type_login: bool
    while_waiting: Callable[[Any], None] | None
    # The site turned the saved login down during this run.
    rejected: bool = False
    # You clicked or typed on the page: from then on the app types nothing there.
    took_over: bool = False
    # When your last click or key reached the page.
    last_input: float = 0.0
    _said: str = ""

    @property
    def with_you(self) -> bool:
        return self.view is not None

    @property
    def types(self) -> bool:
        """Whether the app types the saved login into the forms it finds."""
        return self.type_login and not self.took_over

    def needs_you(self, with_you_note: str, refresh_note: str) -> None:
        """The site wants something only you can give. A refresh stops and says so; while you sign
        in, the app shows the note above the page and keeps waiting for you."""
        if self.view is None:
            log.info("%s: the site needs you: %s", self.provider.key, refresh_note)
            raise NeedsPerson(refresh_note)
        if with_you_note != self._said:
            self._said = with_you_note
            self.view.say(with_you_note)

    def wait(self, page, seconds: float) -> None:
        """Give the page time. While you sign in, your clicks and keys reach it meanwhile."""
        if self.screen is None:
            time.sleep(seconds)
            return
        until = time.monotonic() + seconds
        while True:
            if kinds := self.screen.pump():
                self.last_input = time.monotonic()
                self.took_over = self.took_over or bool(kinds - {"scroll"})
            left = until - time.monotonic()
            if left <= 0:
                return
            try:
                # Pictures of the page arrive only while Playwright waits on Chrome, as here.
                page.wait_for_timeout(min(left, INPUT_EVERY) * 1000)
            except Exception:  # the page is gone: the run finds out on its next look
                time.sleep(min(left, INPUT_EVERY))


def _sign_in_and_read(page, run: _Run) -> int:
    provider, credentials = run.provider, run.credentials
    assert provider.balance_url
    started = time.monotonic()
    username_tries = login_tries = 0
    # When the username, and the whole login, last went in.
    username_at = submitted_at = 0.0
    # What the sign-in page said before the login went in.
    form_said: set[str] = set()
    # When the login form showing now was first seen, and which form it was.
    form_since, form_seen = 0.0, ("", False)
    nudged = False
    last_visit = started
    last_where = last_seen = ""
    reading: int | None = None
    read_at = scrolled_at = 0.0
    # When the run reached the balance page and started looking for the number.
    looking_since: float | None = None

    while True:
        now = time.monotonic()
        if run.view and run.view.stopped:
            log.info("%s: you stopped the sign-in", provider.key)
            raise NeedsPerson(f"You stopped the sign-in to {provider.name}. Click Sign in to try again.")
        if page.is_closed():
            raise NeedsPerson(f"{provider.name}'s page closed before the sign-in finished. Click Sign in to try again.")
        if run.with_you and now >= max(started, run.last_input) + PERSON_TIMEOUT:
            raise NeedsPerson(
                f"The sign-in to {provider.name} timed out before it finished. Click Sign in to try again."
            )
        if not run.with_you and now >= started + QUIET_TIMEOUT:
            run.needs_you("", _finish_note(provider, with_you=False))
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
        form = (where, fields.password is not None)
        if fields.password is None and fields.username is None:
            form_since, form_seen = 0.0, ("", False)
        elif not form_since or form != form_seen:
            form_since, form_seen = now, form
        # The page's own scripts get a moment to set the form up before anything is typed.
        form_ready = now - form_since >= FORM_SETTLE

        if fields.password is not None:
            if (login_tries or not run.type_login) and _REJECTED_WORDS.search(_deep_text(page)):
                if not run.with_you:
                    log.info("%s: the site rejected the login", provider.key)
                    raise LoginRejected(
                        f"{provider.name} didn't take the saved login. Click Sign in to sign in once; "
                        "Award Wallet keeps the login that works."
                    )
                if not run.rejected:
                    log.info("%s: the site rejected the login; waiting for you", provider.key)
                run.rejected = True
                run.needs_you(_rejected_note(provider), "")
            # The form is back, empty, and the page says nothing new (no "try again", no error): the
            # site reset it, as some do while they finish loading. Anything else is left to you.
            cleared = (
                login_tries < LOGIN_TRIES
                and now - submitted_at > RETRY_AFTER
                and _empty(fields.password)
                and not _sentences(_deep_text(page)) - form_said
            )
            if run.types and not run.rejected and form_ready and (not login_tries or cleared):
                if login_tries:
                    log.info("%s: the site cleared the login without saying why; typing it again", provider.key)
                else:
                    form_said = _sentences(_deep_text(page))
                if _type_login(fields, credentials):
                    log.info("%s: submitted the login", provider.key)
                    login_tries += 1
                    submitted_at = time.monotonic()
                run.wait(page, POLL * 2)
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
                    run.wait(page, POLL)
                    continue
            # The site asks to confirm it's you, like Chase's "Let's make sure it's you" (on its
            # dashboard's own address). Only you can do that.
            if (
                reading is None
                and (login_tries or username_tries or run.with_you)
                and time.monotonic() - max(submitted_at, username_at) > SETTLE
                and _asks_who_you_are(page)
            ):
                if not run.with_you:
                    log.info("%s: the site asks to confirm it's you (the page: %s)", provider.key, _title(page))
                run.needs_you(_confirm_note(provider, with_you=True), _confirm_note(provider, with_you=False))
            if at_balance_page:
                looking_since = looking_since or time.monotonic()
                looked = time.monotonic() - looking_since
                if looked > TROUBLE_GRACE and (trouble := _site_trouble(page)):
                    log.info("%s: the site shows an error", provider.key)
                    raise FetchProblem(f"{provider.name} says: “{trouble}” Try again later.")
                if looked > READ_TIMEOUT and not run.with_you:
                    raise FetchProblem(
                        f"Couldn't find your {provider.unit} on {provider.name}'s page. "
                        "The site may have changed; a screenshot was saved for checking."
                    )
                if looked > SCROLL_EVERY and time.monotonic() - scrolled_at > SCROLL_EVERY:
                    scrolled_at = time.monotonic()
                    _scroll_on(page)
            if fields.username is not None and run.types:
                # Sites that ask for the username first and the password on the next screen, on a
                # sign-in page or right on the account page, like United's.
                cleared = username_tries < LOGIN_TRIES and now - username_at > RETRY_AFTER and _empty(fields.username)
                if form_ready and (not username_tries or cleared):
                    if _type_username(fields, credentials):
                        log.info("%s: submitted the username", provider.key)
                        username_tries += 1
                        username_at, nudged = time.monotonic(), False
                    run.wait(page, POLL * 2)
                    continue
                if username_tries and not nudged and now - username_at > NUDGE_AFTER:
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
            not at_balance_page
            and login_tries
            and not run.rejected
            and time.monotonic() - submitted_at > CHALLENGE_GRACE
        ):
            run.needs_you(_finish_note(provider, with_you=True), _finish_note(provider, with_you=False))
        if run.with_you and run.while_waiting:
            run.while_waiting(page)
        run.wait(page, POLL)
