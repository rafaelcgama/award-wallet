from .base import PASSWORD, CredentialField, Provider
from .registry import register

# Each label must be the whole text of its box, give or take the number itself before or after
# it, like "Membership Rewards® Points", "97,481 Membership Rewards® points" or "Points Balance:
# 97,481". So "Pending Points", "Points Available on Payment" and sentences that mention points
# never count.
_ALONE_BEFORE = r"(?<=^[\d,\s]*)"
_ALONE_AFTER = r"(?=\W*(?:\d[\d,]*\s*(?:pts|points)?\W*)?$)"


@register
class AmericanExpress(Provider):
    key = "amex"
    name = "American Express"
    program = "Membership Rewards"
    category = "bank"
    unit = "points"
    website = "https://www.americanexpress.com"
    rewards_url = "https://global.americanexpress.com/rewards"
    expiration_policy = "Membership Rewards points don't expire while you have a card that earns them."
    credential_fields = (CredentialField("username", "User ID"), PASSWORD)
    # The account home, where Amex lands after signing in. Amex's help pages say it shows your
    # total Membership Rewards points; signed out, it sends you to the sign-in page and back.
    balance_url = "https://global.americanexpress.com/dashboard"
    # Amex shows the points next to pending points, points that come in once you pay, points
    # earned and redeemed this year, and card offers in points. None of those is the balance.
    # There's no reading of the page's plain text either: with that many numbers side by side,
    # better no number than a wrong one.
    balance_labels = (
        _ALONE_BEFORE + r"membership\s*rewards\W*\s*points(?:\s*(?:available|balance))?" + _ALONE_AFTER,
        _ALONE_BEFORE + r"(?:available\s*points|points\s*available)" + _ALONE_AFTER,
        _ALONE_BEFORE + r"(?:current\s*|total\s*)?points\s*balance" + _ALONE_AFTER,
    )
