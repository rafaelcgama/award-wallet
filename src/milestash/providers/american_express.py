from .base import PASSWORD, CredentialField, Provider, TransferPartner, alone
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
    # Checked 2026-11-07 against Roame (updated Jul 27, 2026) and NerdWallet (Jul 24, 2026).
    transfer_partners = (
        TransferPartner("Aer Lingus AerClub", "airline", "1:1"),
        TransferPartner("Aeromexico Rewards", "airline", "1:1.6"),
        TransferPartner("Air Canada Aeroplan", "airline", "1:1"),
        TransferPartner("Air France-KLM Flying Blue", "airline", "1:1"),
        TransferPartner("ANA Mileage Club", "airline", "1:1"),
        TransferPartner("Avianca LifeMiles", "airline", "1:1"),
        TransferPartner("British Airways Club", "airline", "1:1"),
        TransferPartner("Cathay Pacific Asia Miles", "airline", "5:4"),
        TransferPartner("Club Iberia Plus", "airline", "1:1"),
        TransferPartner("Delta SkyMiles", "airline", "1:1"),
        TransferPartner("Emirates Skywards", "airline", "5:4"),
        TransferPartner("JetBlue TrueBlue", "airline", "5:4"),
        TransferPartner("Qantas Frequent Flyer", "airline", "1:1"),
        TransferPartner("Qatar Airways Privilege Club", "airline", "1:1"),
        TransferPartner("Singapore KrisFlyer", "airline", "1:1"),
        TransferPartner("Virgin Atlantic Flying Club", "airline", "1:1"),
        TransferPartner("Choice Privileges", "hotel", "1:1"),
        TransferPartner("Hilton Honors", "hotel", "1:2"),
        TransferPartner("Leaders Club", "hotel", "4:1"),
        TransferPartner("Marriott Bonvoy", "hotel", "1:1"),
    )
