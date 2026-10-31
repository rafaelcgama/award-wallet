"""Loyalty program integrations. Importing this package registers every provider."""

from . import capital_one, chase, united  # noqa: F401  (registers the providers)
from .base import CredentialField, Expiration, FetchResult, Provider
from .registry import UnknownProvider, all_providers, get_provider

__all__ = [
    "CredentialField",
    "Expiration",
    "FetchResult",
    "Provider",
    "UnknownProvider",
    "all_providers",
    "get_provider",
]
