from .base import Provider, TransferPartner
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
    balance_url = "https://myaccounts.capitalone.com/accountSummary"
    balance_patterns = (
        r"(\d[\d,]*)\s*(?:venture\s*)?miles\b",
        r"(?:rewards balance|miles balance|available miles)\D{0,20}?(\d[\d,]*)",
    )
    # Checked 2026-11-07 against Roame (updated Sep 2, 2026) and point.me (Aug 4, 2026).
    transfer_partners = (
        TransferPartner("Aeromexico Rewards", "airline", "1:1"),
        TransferPartner("Air Canada Aeroplan", "airline", "1:1"),
        TransferPartner("Air France-KLM Flying Blue", "airline", "1:1"),
        TransferPartner("Avianca LifeMiles", "airline", "1:1"),
        TransferPartner("British Airways Club", "airline", "1:1"),
        TransferPartner("Cathay Pacific Asia Miles", "airline", "1:1"),
        TransferPartner("Copa ConnectMiles", "airline", "2:1.5"),
        TransferPartner("Emirates Skywards", "airline", "2:1.5"),
        TransferPartner("Etihad Guest", "airline", "1:1"),
        TransferPartner("EVA Infinity MileageLands", "airline", "2:1.5"),
        TransferPartner("Finnair Plus", "airline", "1:1"),
        TransferPartner("JAL Mileage Bank", "airline", "2:1.5"),
        TransferPartner("JetBlue TrueBlue", "airline", "5:3"),
        TransferPartner("Qantas Frequent Flyer", "airline", "1:1"),
        TransferPartner("Qatar Airways Privilege Club", "airline", "1:1"),
        TransferPartner("Singapore KrisFlyer", "airline", "1:1"),
        TransferPartner("TAP Miles&Go", "airline", "1:1"),
        TransferPartner("Turkish Airlines Miles&Smiles", "airline", "1:1"),
        TransferPartner("Virgin Atlantic Flying Club", "airline", "1:1"),
        TransferPartner("Accor Live Limitless", "hotel", "2:1"),
        TransferPartner("Choice Privileges", "hotel", "1:1"),
        TransferPartner("I Prefer Hotel Rewards", "hotel", "1:2"),
        TransferPartner("Wyndham Rewards", "hotel", "1:1"),
    )
