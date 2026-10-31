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
