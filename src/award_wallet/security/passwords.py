"""Password hashing for Award Wallet's own sign-in (Argon2id)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
# Checked against when an email isn't registered, so a failed sign-in takes the same time
# whether or not the account exists.
_UNKNOWN_USER_HASH = _hasher.hash("award-wallet-unknown-user")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Check a password. Pass None for an unknown user to spend the same time and fail."""
    try:
        return _hasher.verify(password_hash or _UNKNOWN_USER_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
