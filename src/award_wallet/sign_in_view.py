"""A site's sign-in, shown inside Award Wallet's own window instead of a Chrome window.

When you click Sign in, the app signs in with the same hidden Chrome it refreshes with, so the
site gets to know the browser that will do the refreshes: confirm it's you once, and later
refreshes need nothing. Capital One, for one, trusts a Chrome window it has seen before but asks
the hidden Chrome for a code every time, as if it were another device.

This module carries the page between that hidden Chrome and the app's window. Chrome sends a
picture of the page each time it changes; your clicks and keys come back as events for the page,
the same as clicking and typing in Chrome itself. The pictures stay in memory while you sign in
and are gone when the sign-in ends. Nothing is written to disk or to the log.
"""

import threading
import unicodedata
from collections import deque
from typing import Any

# Keys passed on by name. Every other key arrives as the text it types, so the page gets exactly
# what you typed, accents and all.
KEYS = frozenset(
    {"Enter", "Backspace", "Tab", "Escape", "Delete", "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown", "Home", "End"}
)
# Limits on what one request may send: a sign-in needs a few clicks and some typing, never more.
MAX_EVENTS = 50
MAX_TEXT = 200
MAX_SCROLL = 5000
# Events waiting for the page. More than this means the page has stopped taking them.
MAX_WAITING = 500


class SignInView:
    """What the window shows of a sign-in in progress, and what you do there. Shared by the thread
    running Chrome and the app's web pages, so every method takes the lock."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._changed = threading.Condition()
        self._picture: bytes | None = None
        self._number = 0
        # Counts every change the window shows: a picture, a note, the end.
        self._version = 0
        self._width = 0.0
        self._height = 0.0
        self._events: deque[dict[str, Any]] = deque()
        self._note = ""
        # "open" while you sign in, then "done" (the balance was read) or "ended" (it wasn't).
        self._state = "open"
        self._stopped = False

    # The Chrome side.

    def show(self, picture: bytes, width: float, height: float) -> None:
        """A new picture of the page, which is width by height in the page's own pixels."""
        with self._changed:
            if self._state != "open":
                return
            self._picture, self._width, self._height = picture, float(width), float(height)
            self._number += 1
            self._version += 1
            self._changed.notify_all()

    def say(self, note: str) -> None:
        """What the site wants from you, shown above the page."""
        with self._changed:
            if note != self._note:
                self._note = note
                self._version += 1
                self._changed.notify_all()

    def take(self) -> list[dict[str, Any]]:
        """The clicks and keys sent since the last call, in the order you made them."""
        with self._changed:
            events = list(self._events)
            self._events.clear()
            return events

    def end(self, done: bool) -> None:
        with self._changed:
            self._state = "done" if done else "ended"
            self._picture = None
            self._events.clear()
            self._version += 1
            self._changed.notify_all()

    @property
    def stopped(self) -> bool:
        with self._changed:
            return self._stopped

    # The window side.

    @property
    def note(self) -> str:
        with self._changed:
            return self._note

    @property
    def is_open(self) -> bool:
        with self._changed:
            return self._state == "open" and not self._stopped

    def picture(self) -> bytes | None:
        """The newest picture of the page, a JPEG."""
        with self._changed:
            return self._picture

    def status(self, after: int = -1, timeout: float = 0) -> dict[str, Any]:
        """Where the sign-in is, once something changed since the status whose version is `after`,
        or after `timeout` seconds. picture is the number of the newest picture (0 for none yet)."""
        with self._changed:
            self._changed.wait_for(lambda: self._version > after, timeout=timeout)
            return {
                "version": self._version,
                "state": "ended" if self._stopped and self._state == "open" else self._state,
                "note": self._note,
                "picture": self._number if self._picture else 0,
                "width": self._width,
                "height": self._height,
            }

    def send(self, events: Any) -> None:
        """Your clicks and keys, for the page. Raises ValueError for anything else."""
        cleaned = [self._clean(event) for event in _as_list(events)]
        with self._changed:
            if self._state != "open" or self._stopped:
                return
            if len(self._events) + len(cleaned) > MAX_WAITING:
                raise ValueError("The page isn't taking clicks or keys right now.")
            self._events.extend(cleaned)

    def stop(self) -> None:
        """You closed the sign-in before it finished."""
        with self._changed:
            self._stopped = True
            self._events.clear()
            self._version += 1
            self._changed.notify_all()

    def _clean(self, event: Any) -> dict[str, Any]:
        """One event, checked and rebuilt from what's expected, so nothing else reaches Chrome."""
        if not isinstance(event, dict):
            raise ValueError("Not an event.")
        kind = event.get("kind")
        if kind == "click":
            return {"kind": "click", **self._place(event)}
        if kind == "scroll":
            dx, dy = (_number(event.get(axis), -MAX_SCROLL, MAX_SCROLL) for axis in ("dx", "dy"))
            return {"kind": "scroll", **self._place(event), "dx": dx, "dy": dy}
        if kind == "text":
            text = event.get("text")
            if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT or not _typeable(text):
                raise ValueError(f"Text to type must be 1 to {MAX_TEXT} characters you can type.")
            return {"kind": "text", "text": text}
        if kind == "key":
            if event.get("key") not in KEYS:
                raise ValueError("Not a key the page takes.")
            return {"kind": "key", "key": event["key"], "shift": event.get("shift") is True}
        raise ValueError("Not an event.")

    def _place(self, event: dict[str, Any]) -> dict[str, float]:
        with self._changed:
            width, height = self._width, self._height
        return {"x": _number(event.get("x"), 0, width), "y": _number(event.get("y"), 0, height)}


def _as_list(events: Any) -> list[Any]:
    if not isinstance(events, list) or not 0 < len(events) <= MAX_EVENTS:
        raise ValueError(f"Send 1 to {MAX_EVENTS} events at a time.")
    return events


def _number(value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value != value:
        raise ValueError("Not a number.")
    if not low <= value <= high:
        raise ValueError("Outside the page.")
    return float(value)


def _typeable(text: str) -> bool:
    """Characters a keyboard types: no control characters (Enter and Tab come as keys)."""
    return not any(unicodedata.category(character) in ("Cc", "Cs") for character in text)
