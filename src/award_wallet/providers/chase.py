from .base import Provider, TransferPartner
from .registry import register


@register
class Chase(Provider):
    key = "chase"
    name = "Chase"
    program = "Ultimate Rewards"
    category = "bank"
    unit = "points"
    website = "https://www.chase.com"
    rewards_url = "https://ultimaterewards.chase.com"
    expiration_policy = "Ultimate Rewards points don't expire while the card account is open."
    # Signed in, this opens on one of Chase's numbered servers, like secure07c.chase.com.
    balance_url = "https://secure.chase.com/web/auth/dashboard"
    # The dashboard's Rewards box lists every card's rewards: "163,918 Ultimate Rewards® points"
    # next to the MileagePlus miles a United card earns. Only the first is this program's.
    balance_labels = (r"ultimate\s*rewards\W*(?:points|pts)\b",)
    # Checked 2026-11-07. Hyatt went to 4:3 on Oct 1, 2026 for Sapphire Preferred and Ink Business
    # Preferred; Sapphire Reserve stays 1:1.
    transfer_partners = (
        TransferPartner("Aer Lingus AerClub", "airline", "1:1"),
        TransferPartner("Air Canada Aeroplan", "airline", "1:1"),
        TransferPartner("Air France-KLM Flying Blue", "airline", "1:1"),
        TransferPartner("British Airways Club", "airline", "1:1"),
        TransferPartner("Club Iberia Plus", "airline", "1:1"),
        TransferPartner("JetBlue TrueBlue", "airline", "1:1"),
        TransferPartner("Singapore KrisFlyer", "airline", "1:1"),
        TransferPartner("Southwest Rapid Rewards", "airline", "1:1"),
        TransferPartner("United MileagePlus", "airline", "1:1"),
        TransferPartner("Virgin Atlantic Flying Club", "airline", "1:1"),
        TransferPartner("IHG One Rewards", "hotel", "1:1"),
        TransferPartner("Marriott Bonvoy", "hotel", "1:1"),
        TransferPartner("Wyndham Rewards", "hotel", "1:1"),
        TransferPartner("World of Hyatt", "hotel", "1:1", "4:3 with Sapphire Preferred or Ink Business Preferred"),
    )
