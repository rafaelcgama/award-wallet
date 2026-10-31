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
    balance_url = "https://secure.chase.com/web/auth/dashboard"
    balance_patterns = (
        r"(\d[\d,]*)\s*(?:ultimate rewards(?:®)?\s*)?(?:available\s*)?(?:pts|points)\b",
        r"(?:available points|points balance|ultimate rewards(?:®)?)\D{0,20}?(\d[\d,]*)",
    )
