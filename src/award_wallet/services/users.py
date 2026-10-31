import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from award_wallet.models import User
from award_wallet.security.passwords import hash_password, needs_rehash, verify_password

from .errors import InvalidInput

MIN_PASSWORD_LENGTH = 10


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, *, email: str, password: str, display_name: str = "") -> User:
    email = normalize_email(email)
    local_part, at, domain = email.partition("@")
    if not (local_part and at and "." in domain) or len(email) > 320:
        raise InvalidInput("Enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidInput(f"Use at least {MIN_PASSWORD_LENGTH} characters for your password.")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise InvalidInput("An account with that email already exists.")

    user = User(
        email=email,
        display_name=(display_name.strip() or local_part)[:100],
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    return user


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if not verify_password(user.password_hash if user else None, password):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
    return user


def owner(db: Session) -> User:
    """The single person using the Mac app: the first account, created on first launch."""
    user = db.scalar(select(User).order_by(User.created_at).limit(1))
    if user is None:
        # Nobody signs in to the Mac app, so this password is never used.
        user = User(email="me@localhost", display_name="Me", password_hash=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        db.commit()
    return user
