from sqlalchemy import select
from sqlalchemy.orm import Session

from award_wallet.models import User

# Nobody signs in to the app, so the owner's password field holds a value no password matches.
NO_PASSWORD = "!"


def owner(db: Session) -> User:
    """The one person using the app: the first account, created on first launch."""
    user = db.scalar(select(User).order_by(User.created_at).limit(1))
    if user is None:
        user = User(email="me@localhost", display_name="Me", password_hash=NO_PASSWORD)
        db.add(user)
        db.commit()
    return user
