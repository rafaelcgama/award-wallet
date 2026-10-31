from .base import Provider
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
