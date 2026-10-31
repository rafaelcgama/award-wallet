"""Fetches balances in the background, one program at a time, so pages never wait on a bank site."""

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from award_wallet import fetching
from award_wallet.models import BalanceSource, LoyaltyAccount, SyncStatus, utcnow
from award_wallet.providers import get_provider
from award_wallet.security.vault import Vault

from . import accounts, balances

log = logging.getLogger(__name__)


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
        screenshots_dir: Path | None = None,
        fetch: Callable[..., fetching.Fetched] = fetching.fetch_balance,
    ):
        self._sessions, self._vault, self._fetch = sessions, vault, fetch
        self._screenshots_dir = screenshots_dir
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._waiting: set[str] = set()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def busy(self) -> set[str]:
        """Accounts waiting for or in the middle of a fetch."""
        with self._lock:
            return set(self._waiting)

    def refresh_all(self, db: Session, user_id: str) -> int:
        """Queue a quiet fetch of every program that can be fetched. Returns how many were queued.

        Programs that need you (a code, or a login the site rejected) are skipped: retrying them
        in the background can't succeed and could get the account locked.
        """
        queued = 0
        for account in accounts.list_accounts(db, user_id):
            if can_fetch(account) and account.sync_status != SyncStatus.NEEDS_LOGIN:
                queued += self._enqueue(_Job(account.id, with_person=False))
        return queued

    def refresh_one(self, account: LoyaltyAccount) -> bool:
        return can_fetch(account) and self._enqueue(_Job(account.id, with_person=False))

    def sign_in(self, account: LoyaltyAccount) -> bool:
        """Open a visible window for this program so you can finish the sign-in."""
        return can_fetch(account) and self._enqueue(_Job(account.id, with_person=True))

    def wait(self, timeout: float = 600) -> None:
        """Block until the queue is empty (for tests and the command line)."""
        self._jobs.join()

    def _enqueue(self, job: _Job) -> bool:
        with self._lock:
            if job.account_id in self._waiting:
                return False
            self._waiting.add(job.account_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, name="award-wallet-refresh", daemon=True)
                self._worker.start()
        self._jobs.put(job)
        return True

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                self._run(job)
            except Exception:
                log.exception("Refreshing %s failed", job.account_id)
            finally:
                with self._lock:
                    self._waiting.discard(job.account_id)
                self._jobs.task_done()

    def _run(self, job: _Job) -> None:
        with self._sessions() as db:
            account = db.get(LoyaltyAccount, job.account_id)
            if account is None or not can_fetch(account):
                return
            provider = get_provider(account.provider)
            credentials = accounts.read_credentials(self._vault, account) or {}
            state = accounts.read_session_state(self._vault, account)
            screenshot = self._screenshots_dir / f"{provider.key}.png" if self._screenshots_dir else None

            try:
                result = self._fetch(
                    provider, credentials, state, with_person=job.with_person, screenshot_to=screenshot
                )
            except (fetching.NeedsPerson, fetching.LoginRejected) as exc:
                self._finish(db, account, SyncStatus.NEEDS_LOGIN, str(exc))
                return
            except fetching.FetchProblem as exc:
                self._finish(db, account, SyncStatus.ERROR, str(exc))
                return
            except Exception:
                log.exception("Fetching %s failed", provider.key)
                self._finish(db, account, SyncStatus.ERROR, f"Couldn't reach {provider.name}. Try again later.")
                return

            accounts.save_session_state(self._vault, account, result.session_state)
            account.last_synced_at = utcnow()
            self._finish(db, account, SyncStatus.OK, None, commit=False)
            balances.record_balance(db, account, balance=result.balance, source=BalanceSource.SYNC)

    @staticmethod
    def _finish(db: Session, account: LoyaltyAccount, status: SyncStatus, message: str | None, commit=True) -> None:
        account.sync_status = status
        account.sync_message = message
        if commit:
            db.commit()
