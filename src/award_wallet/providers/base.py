"""The contract every loyalty program integration follows.

To add a program, create a module in this package with a Provider subclass decorated with
@register, then import the module in providers/__init__.py.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import ClassVar


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool = False


USERNAME = CredentialField("username", "Username")
PASSWORD = CredentialField("password", "Password", secret=True)


def alone(words: str) -> str:
    """A balance label that must be the whole text of its box, give or take the number itself
    before or after it: "Available Miles", "52,300 available miles" or "Available Miles: 52,300".
    For pages that show the balance among look-alikes, like "Pending Miles", "Points Available on
    Payment" or a sentence that mentions miles, none of which may count."""
    return r"(?<=^[\d,\s]*)(?:" + words + r")(?=\W*(?:\d[\d,]*\s*(?:pts|points|miles)?\W*)?$)"


@dataclass(frozen=True)
class Expiration:
    expires_on: date
    # None means the whole balance expires on that date, or the site doesn't say how much.
    amount: int | None = None


@dataclass(frozen=True)
class TransferPartner:
    name: str
    kind: str  # "airline" or "hotel"
    ratio: str  # your points to the partner's, like "1:1"
    # When the ratio depends on something, like which card you have.
    note: str | None = None


@dataclass
class FetchResult:
    balance: int
    expirations: list[Expiration] = field(default_factory=list)


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
    # The words that name the balance on that page, as regular expressions (case-insensitive, and
    # written so JavaScript reads them the same way). The balance is the number shown with them,
    # in the same box, like "163,918" above "Ultimate Rewards® points". Tried first, and the
    # right choice when a page shows several programs' balances.
    balance_labels: ClassVar[tuple[str, ...]] = ()
    # Regular expressions run over that page's text; group 1 is the balance, like "52,300".
    balance_patterns: ClassVar[tuple[str, ...]] = ()
    # Regular expressions run over the balance page's text that find when the balance expires;
    # group 1 is the date, like "Jan 3, 2028" or "01/03/2028". Matched on the words around the date,
    # never on where it sits in the page, so a redesign of the page doesn't lose it.
    expiration_patterns: ClassVar[tuple[str, ...]] = ()
    # How the card says when the whole balance expires, while that's more than three months away;
    # {date} stands for the date. Without one it says "The balance expires on {date}."
    expires_on_text: ClassVar[str | None] = None
    # What to do when an expiration is near (see EXPIRES_SOON), shown with the alert.
    keep_alive_hint: ClassVar[str] = "Use them before then, or check the program's site."
    # Programs the points move to, for banks' points. Banks change these a few times a year, so
    # each list says when it was last checked against the bank's own page.
    transfer_partners: ClassVar[tuple[TransferPartner, ...]] = ()

    @property
    def supports_fetch(self) -> bool:
        return bool(self.balance_url and (self.balance_labels or self.balance_patterns))
