"""The contract every loyalty program integration follows.

To add a program, create a module in this package with a Provider subclass decorated with
@register, then import the module in providers/__init__.py.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool = False


USERNAME = CredentialField("username", "Username")
PASSWORD = CredentialField("password", "Password", secret=True)


@dataclass(frozen=True)
class Expiration:
    expires_on: date
    # None means the whole balance expires on that date, or the site doesn't say how much.
    amount: int | None = None


@dataclass
class FetchResult:
    balance: int
    expirations: list[Expiration] = field(default_factory=list)
    # Cookies and storage to reuse on the next fetch, so the login isn't repeated each time.
    session_state: dict[str, Any] | None = None


class Provider:
    # Stored in the database for every linked account, so never rename one.
    key: ClassVar[str]
    name: ClassVar[str]
    program: ClassVar[str]
    category: ClassVar[str]  # "airline", "bank" or "hotel"
    unit: ClassVar[str]  # what the balance counts, e.g. "miles" or "points"
    website: ClassVar[str]
    # Where you spend the points: award booking or the transfer-partner portal.
    rewards_url: ClassVar[str]
    # Shown when a balance has no expiration date, so "no date" never looks like missing data.
    expiration_policy: ClassVar[str]
    credential_fields: ClassVar[tuple[CredentialField, ...]] = (USERNAME, PASSWORD)

    # Automatic fetching (see award_wallet.fetching). The page that shows the balance once signed
    # in; opening it while signed out sends you to the site's sign-in page.
    balance_url: ClassVar[str | None] = None
    # Regular expressions run over that page's text; group 1 is the balance, like "52,300".
    balance_patterns: ClassVar[tuple[str, ...]] = ()

    @property
    def supports_fetch(self) -> bool:
        return bool(self.balance_url and self.balance_patterns)
