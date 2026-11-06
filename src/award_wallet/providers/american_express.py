from .base import PASSWORD, CredentialField, Provider, alone
from .registry import register


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
    # earned and redeemed this year, and card offers in points. None of those is the balance, so
    # each label must be its box's whole text: "Membership Rewards® Points", "Available Points" or
    # "Points Balance", never "Pending Points" or "Points Available on Payment". There's no
    # reading of the page's plain text either: with that many numbers side by side, better no
    # number than a wrong one.
    balance_labels = (
        alone(r"membership\s*rewards\W*\s*points(?:\s*(?:available|balance))?"),
        alone(r"available\s*points|points\s*available"),
        alone(r"(?:current\s*|total\s*)?points\s*balance"),
    )
