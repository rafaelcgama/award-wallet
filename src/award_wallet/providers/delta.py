from .base import PASSWORD, CredentialField, Provider, alone
from .registry import register


@register
class Delta(Provider):
    key = "delta"
    name = "Delta Air Lines"
    program = "SkyMiles"
    category = "airline"
    unit = "miles"
    website = "https://www.delta.com"
    rewards_url = "https://www.delta.com/flight-search/book-a-flight"
    expiration_policy = "SkyMiles miles don't expire."
    # Delta signs in with the SkyMiles number (or username) and password, then may ask to confirm
    # it's you with a code by text or email, or in the Fly Delta app.
    credential_fields = (CredentialField("username", "SkyMiles number or username"), PASSWORD)
    # The SkyMiles overview: the miles you can spend lead the page, next to Book with Miles.
    # Signed out, it sends you to delta.com's sign-in page and back.
    balance_url = "https://www.delta.com/myskymiles/overview"
    # The page also shows Medallion Qualifying Dollars, pending and upcoming credit from booked
    # trips, lifetime miles toward Million Miler and card offers in miles. None of those is the
    # balance, so each label must be its box's whole text, like "Available Miles", never
    # "Pending Miles" or "Earn 50,000 bonus miles", and the page's plain text isn't read. Better
    # no number than a wrong one.
    balance_labels = (
        alone(r"available\s*miles|miles\s*available"),
        alone(r"(?:skymiles\W*\s*)?(?:mileage|miles)\s*balance"),
    )
