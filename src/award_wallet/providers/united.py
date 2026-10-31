from .base import PASSWORD, CredentialField, Provider
from .registry import register


@register
class United(Provider):
    key = "united"
    name = "United Airlines"
    program = "MileagePlus"
    category = "airline"
    unit = "miles"
    website = "https://www.united.com/en/us/myunited"
    rewards_url = "https://www.united.com/en/us"
    expiration_policy = "MileagePlus miles don't expire."
    credential_fields = (CredentialField("username", "MileagePlus number or username"), PASSWORD)
