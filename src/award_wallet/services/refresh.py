"""Fetches balances in the background, a few programs at a time, so pages never wait on a bank site."""

import logging
import queue
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from award_wallet import fetching
from award_wallet.models import BalanceSource, LoyaltyAccount, SyncStatus, utcnow
from award_wallet.providers import get_provider
from award_wallet.security.vault import Vault
from award_wallet.sign_in_view import SignInView

from . import accounts, balances

log = logging.getLogger(__name__)

# Programs fetched at the same time. Each one runs its own Chrome, so keep it small.
MAX_PARALLEL = 3


@dataclass(frozen=True)
class _Job:
    account_id: str
    with_person: bool


def can_fetch(account: LoyaltyAccount) -> bool:
    return account.credentials_encrypted is not None and get_provider(account.provider).supports_fetch


class Refresher:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        vault: Vault,
        *,
        browser_dir: Path | None = None,
        screenshots_dir: Path | None = None,
        fetch: Callable[..., int] = fetching.fetch_balance,
    ):
        self._sessions, self._vault, self._fetch = sessions, vault, fetch
        # One Chrome profile per program, kept between runs so the site remembers this Mac.
        self._browser_dir = browser_dir or Path(tempfile.gettempdir()) / "award-wallet-browser"
        self._screenshots_dir = screenshots_dir
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._waiting: set[str] = set()
        # Sign-ins shown in the app's window, by account, from the click until they end.
        self._views: dict[str, SignInView] = {}
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []

    def busy(self) -> set[str]:
        """Accounts waiting for or in the middle of a fetch."""
        with self._lock:
            return set(self._waiting)

    def needs_you(self) -> dict[str, str]:
        """Accounts you're signing in to, with a note saying what the site wants from you."""
        with self._lock:
            views = dict(self._views)
        return {account_id: view.note for account_id, view in views.items() if view.is_open}

    def view(self, account_id: str) -> SignInView | None:
        """The sign-in to this account that's open in the app's window, if there is one."""
        with self._lock:
            view = self._views.get(account_id)
        return view if view and view.is_open else None

    def refresh_all(self, db: Session, user_id: str) -> int:
        """Queue a quiet fetch of every program that can be fetched. Returns how many were queued.

        A program whose site rejected the saved login is skipped until you save it again:
        retrying a wrong password could get the account locked.
        """
        queued = 0
        for account in accounts.list_accounts(db, user_id):
            if can_fetch(account) and account.sync_status != SyncStatus.LOGIN_REJECTED:
                queued += self._enqueue(_Job(account.id, with_person=False))
        return queued

    def refresh_one(self, account: LoyaltyAccount) -> bool:
        return can_fetch(account) and self._enqueue(_Job(account.id, with_person=False))

    def sign_in(self, account: LoyaltyAccount) -> SignInView | None:
        """Sign in to this program with you: the hidden Chrome that refreshes it signs in, and its
        page shows in the app's window, where you finish what the site asks. None if the program
        is being refreshed right now."""
        if not can_fetch(account):
            return None
        view = SignInView(get_provider(account.provider).name)
        return view if self._enqueue(_Job(account.id, with_person=True), view) else None

    def stop_sign_in(self, account_id: str) -> None:
        if view := self.view(account_id):
            view.stop()

    def wait(self, timeout: float = 600) -> None:
        """Block until the queue is empty (for tests and the command line)."""
        self._jobs.join()

    def browser_profile(self, account_id: str) -> Path:
        # An account's id names a folder inside the Browser folder, never one outside it.
        if account_id in ("", ".", "..") or Path(account_id).name != account_id:
            raise ValueError(f"Not an account id: {account_id!r}")
        return self._browser_dir / account_id

    def forget_browser(self, account_id: str) -> None:
        """Delete a program's Chrome profile: its cookies, and with them the site's memory of this Mac."""
        shutil.rmtree(self.browser_profile(account_id), ignore_errors=True)

    def _enqueue(self, job: _Job, view: SignInView | None = None) -> bool:
        with self._lock:
            if job.account_id in self._waiting:
                return False
            self._waiting.add(job.account_id)
            if view:
                self._views[job.account_id] = view
            self._workers = [worker for worker in self._workers if worker.is_alive()]
            if len(self._workers) < MAX_PARALLEL:
                worker = threading.Thread(target=self._work, name="award-wallet-refresh", daemon=True)
                worker.start()
                self._workers.append(worker)
        self._jobs.put(job)
        return True

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            started = time.monotonic()
            done = False
            try:
                done = self._run(job)
            except Exception:
                log.exception("Refreshing %s failed", job.account_id)
            else:
                log.info("Refresh of %s took %.1fs", job.account_id, time.monotonic() - started)
            finally:
                with self._lock:
                    self._waiting.discard(job.account_id)
                    view = self._views.pop(job.account_id, None)
                if view:
                    view.end(done)
                self._jobs.task_done()

    def _run(self, job: _Job) -> bool:
        """Fetch one program's balance. Whether it was read."""
        with self._sessions() as db:
            account = db.get(LoyaltyAccount, job.account_id)
            if account is None or not can_fetch(account):
                return False
            provider = get_provider(account.provider)
            credentials = accounts.read_credentials(self._vault, account) or {}
            screenshot = self._screenshots_dir / f"{provider.key}.png" if self._screenshots_dir else None
            # Versions before 0.5 kept the site's cookies in the database: carry them into the new
            # Chrome profile once, so the site still knows this Mac.
            old_state = accounts.read_session_state(self._vault, account) or {}

            # A login you signed in with, after the site turned the saved one down.
            learned: dict[str, str] = {}
            rejected = account.sync_status == SyncStatus.LOGIN_REJECTED
            with self._lock:
                view = self._views.get(job.account_id) if job.with_person else None
            try:
                balance = self._fetch(
                    provider,
                    credentials,
                    self.browser_profile(account.id),
                    view=view,
                    # The site turned the saved login down last time, so you sign in yourself
                    # instead of the app trying it again.
                    type_login=not (view and rejected),
                    screenshot_to=screenshot,
                    seed_cookies=old_state.get("cookies"),
                    on_new_login=learned.update,
                )
            except Exception as exc:
                status, message = self._outcome(provider, exc)
                if view and rejected and status == SyncStatus.NEEDS_LOGIN:
                    # A sign-in you didn't finish leaves the saved login turned down, so refreshes
                    # still don't try it: a wrong password tried again could lock the account.
                    status = SyncStatus.LOGIN_REJECTED
                if not isinstance(exc, fetching.ChromeMissing):
                    account.session_state_encrypted = None
                self._finish(db, account, status, message)
                return False

            if learned:
                accounts.remember_login(self._vault, account, learned)
                log.info("%s: kept the login you signed in with", provider.key)
            account.session_state_encrypted = None
            account.last_synced_at = utcnow()
            self._finish(db, account, SyncStatus.OK, None, commit=False)
            balances.record_balance(db, account, balance=balance, source=BalanceSource.SYNC)
            return True

    @staticmethod
    def _outcome(provider, exc: Exception) -> tuple[SyncStatus, str]:
        """The status and message a failed fetch leaves on the program."""
        if isinstance(exc, fetching.LoginRejected):
            log.info("%s rejected the login: %s", provider.key, exc)
            return SyncStatus.LOGIN_REJECTED, str(exc)
        if isinstance(exc, fetching.NeedsPerson):
            log.info("%s needs you: %s", provider.key, exc)
            return SyncStatus.NEEDS_LOGIN, str(exc)
        if isinstance(exc, fetching.FetchProblem):
            log.warning("%s fetch failed: %s", provider.key, exc)
            return SyncStatus.ERROR, str(exc)
        log.error("Fetching %s failed", provider.key, exc_info=exc)
        return SyncStatus.ERROR, f"Couldn't reach {provider.name}. Try again later."

    @staticmethod
    def _finish(db: Session, account: LoyaltyAccount, status: SyncStatus, message: str | None, commit=True) -> None:
        account.sync_status = status
        account.sync_message = message
        if commit:
            db.commit()
