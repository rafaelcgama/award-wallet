from .base import PASSWORD, CredentialField, Provider
from .registry import register


@register
class American(Provider):
    key = "american"
    name = "American Airlines"
    program = "AAdvantage"
    category = "airline"
    unit = "miles"
    website = "https://www.aa.com"
    rewards_url = "https://www.aa.com/booking/find-flights"
    expiration_policy = (
        "AAdvantage miles stay active as long as you earn or spend some every 24 months, and don't "
        "expire while you have an AAdvantage credit card."
    )
    # American dropped the last name from its sign-in: the AAdvantage number (or username) and
    # password are enough.
    credential_fields = (CredentialField("username", "AAdvantage number or username"), PASSWORD)
    # Signed out, this sends you to aa.com's sign-in page and back here after.
    balance_url = "https://www.aa.com/aadvantage-program/profile/account-summary"
    # The account summary names the balance "Award miles" (or "AAdvantage® miles"). Loyalty
    # Points, which count toward status, sit nearby and must never be read as miles.
    balance_labels = (
        r"award\s*miles\b",
        r"aadvantage\W*\s*miles\b",
        r"(?:mileage|miles)\s*balance\b",
    )
    # Failing those, only a number named as award miles in the page's text: the page also shows
    # lifetime miles toward Million Miler and card offers in miles, and none of those is the
    # balance. Better no number than a wrong one.
    balance_patterns = (
        r"award\s*miles\W{0,3}\s*(\d[\d,]*)",
        r"(\d[\d,]*)\s*award\s*miles\b",
    )
