"""Per-session tokens that every form posts back, so other sites can't submit forms as you."""

import hmac
import secrets
from collections.abc import MutableMapping
from typing import Any

SESSION_KEY = "csrf"


def token_for(session: MutableMapping[str, Any]) -> str:
    token = session.get(SESSION_KEY)
    if not token:
        token = session[SESSION_KEY] = secrets.token_urlsafe(32)
    return token


def is_valid(session: MutableMapping[str, Any], submitted: str) -> bool:
    expected = session.get(SESSION_KEY)
    return bool(expected and submitted) and hmac.compare_digest(expected, submitted)
