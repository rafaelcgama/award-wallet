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
    balance_url = "https://www.united.com/en/us/myunited"
    balance_patterns = (
        r"(\d[\d,]*)\s*(?:award\s*)?miles\b",
        r"(?:miles balance|mileageplus miles|award miles)\D{0,20}?(\d[\d,]*)",
    )
