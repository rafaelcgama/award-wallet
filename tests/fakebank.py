"""A pretend rewards site for testing the fetcher: sign-in, a one-time code, a balance page.

The code is only asked for until the browser is trusted, like real banks do.
"""

import secrets
import socket
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

USERNAME, PASSWORD, CODE = "rafael", "hunter2", "123456"


def page(body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html><body><input type='search' placeholder='Search'>{body}</body></html>")


# What the balance page shows once signed in.
BALANCE_PAGES = {
    "normal": "<h1>Rewards</h1><p>Total rewards balance</p><p>{balance:,} Miles</p>",
    # Counts up to the balance, like some dashboards do.
    "counting": (
        "<h1>Rewards</h1><p><span id=n>0</span> Miles</p><script>let v = 0; const t = setInterval(() => {{"
        " v = Math.min({balance}, v + Math.ceil({balance} / 15)); n.textContent = v.toLocaleString('en-US');"
        " if (v >= {balance}) clearInterval(t); }}, 100);</script>"
    ),
    "trouble": (
        "<h1>Good Afternoon</h1><p>We can’t access your account information right now, but we’re working on it.</p>"
    ),
    "empty": "<h1>Rewards</h1><p>Total rewards balance</p>",
    # The balance box loads only once it's scrolled into view.
    "below": (
        "<h1>Rewards</h1><div style='height: 3000px'></div><p id=box>Loading…</p><script>"
        "new IntersectionObserver((seen) => {{ if (seen[0].isIntersecting) box.textContent = '{balance:,} Miles'; }})"
        ".observe(box);</script>"
    ),
}


class FakeBank:
    def __init__(self, *, two_step: bool = False, in_iframe: bool = False, balance: int = 52300, shows: str = "normal"):
        self.two_step, self.in_iframe, self.balance, self.shows = two_step, in_iframe, balance, shows
        self.sessions: set[str] = set()
        self.trusted: set[str] = set()
        self.codes_asked = 0

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/account", self.account),
                Route("/signin", self.signin, methods=["GET", "POST"]),
                Route("/signin/form", self.signin_form, methods=["GET", "POST"]),
                Route("/verify", self.verify, methods=["GET", "POST"]),
            ]
        )

    async def account(self, request: Request):
        if request.cookies.get("session") not in self.sessions:
            return RedirectResponse("/signin", 303)
        return page(BALANCE_PAGES[self.shows].format(balance=self.balance))

    async def signin(self, request: Request):
        if self.in_iframe and request.method == "GET":
            return page("<h1>Sign in</h1><iframe src='/signin/form' width=500 height=400></iframe>")
        return await self.signin_form(request)

    async def signin_form(self, request: Request):
        if request.method == "GET":
            return page(self._form())
        form = await request.form()
        username = form.get("username", "")
        if self.two_step and "password" not in form:
            return page(self._form(username=str(username)))
        if username != USERNAME or form.get("password") != PASSWORD:
            return page("<p>The username or password you entered is incorrect.</p>" + self._form())
        if request.cookies.get("device") in self.trusted:
            return self._signed_in(request)
        return RedirectResponse("/verify", 303)

    async def verify(self, request: Request):
        if request.method == "GET":
            self.codes_asked += 1
            return page(
                "<h1>Enter the code we texted you</h1><form method=post><input name=code inputmode=numeric>"
                "<button>Verify</button></form>"
            )
        form = await request.form()
        if form.get("code") != CODE:
            return page("<p>Wrong code</p>")
        response = self._signed_in(request)
        device = secrets.token_hex(8)
        self.trusted.add(device)
        response.set_cookie("device", device, max_age=86400 * 365)
        return response

    def _signed_in(self, request: Request):
        session = secrets.token_hex(8)
        self.sessions.add(session)
        response = RedirectResponse("/account", 303)
        response.set_cookie("session", session)
        return response

    def _form(self, username: str | None = None) -> str:
        if self.two_step and username is None:
            return (
                "<form method=post action='/signin/form'><input name=username autocomplete=username>"
                "<button>Continue</button></form>"
            )
        hidden = (
            f"<input type=hidden name=username value='{username}'>"
            if username
            else ("<input name=username autocomplete=username>")
        )
        target = "_top" if self.in_iframe else "_self"
        return (
            f"<form method=post action='/signin/form' target='{target}'>{hidden}"
            "<input type=password name=password><button>Sign in</button></form>"
        )

    def expire_sessions(self) -> None:
        self.sessions.clear()


def serve(bank: FakeBank):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(bank.app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    return server, thread, f"http://127.0.0.1:{port}"
