"""Keeps the app's pages to its own window.

Every response tells the window to run no scripts or styles but the app's own, to never show the
page inside another site, to send no address along to other sites, and to keep no copy of the page
on disk. Requests that another website sends to the app are turned away before they reach a page.
"""

from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
    ]
)

HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# Requests that change something.
_CHANGES = {"POST", "PUT", "PATCH", "DELETE"}


class LockedToTheWindow:
    """Adds the headers above to every response, and turns away requests from other sites."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # The pages show your balances: nothing but the app's own files may be kept on disk.
        keep = scope["path"].startswith("/static/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    headers[name] = value
                if not keep:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        if from_another_site(scope):
            response = PlainTextResponse("Award Wallet only answers its own window.", status_code=403)
            await response(scope, receive, send_with_headers)
            return
        await self.app(scope, receive, send_with_headers)


def from_another_site(scope: Scope) -> bool:
    """Whether a web page from another site sent this request, as the browser tells it."""
    headers = Headers(scope=scope)
    if headers.get("sec-fetch-site") == "cross-site":
        return True
    if scope["method"] in _CHANGES:
        # Browsers say where a form was sent from. "null" hides it, which the window's own forms
        # may do too, so that one is left to the form's token.
        origin = headers.get("origin")
        if origin and origin != "null" and urlsplit(origin).netloc != headers.get("host"):
            return True
    return False
