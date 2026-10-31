from .base import Provider
from .registry import register


@register
class CapitalOne(Provider):
    key = "capital_one"
    name = "Capital One"
    program = "Capital One Miles"
    category = "bank"
    unit = "miles"
    website = "https://www.capitalone.com"
    rewards_url = "https://travel.capitalone.com"
    expiration_policy = "Capital One miles don't expire for the life of the account."
