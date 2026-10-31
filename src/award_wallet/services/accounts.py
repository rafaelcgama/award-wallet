from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from award_wallet.models import LoyaltyAccount, SyncStatus, new_id
from award_wallet.providers import Provider, get_provider
from award_wallet.security.vault import Vault

from .errors import AccountNotFound, InvalidInput

MAX_LABEL_LENGTH = 100


def list_accounts(db: Session, user_id: str) -> list[LoyaltyAccount]:
    query = (
        select(LoyaltyAccount)
        .where(LoyaltyAccount.user_id == user_id)
        .order_by(LoyaltyAccount.created_at, LoyaltyAccount.id)
    )
    return list(db.scalars(query))


def get_account(db: Session, user_id: str, account_id: str) -> LoyaltyAccount:
    account = db.scalar(
        select(LoyaltyAccount).where(LoyaltyAccount.id == account_id, LoyaltyAccount.user_id == user_id)
    )
    if account is None:
        raise AccountNotFound(account_id)
    return account


def link_account(
    db: Session,
    vault: Vault,
    *,
    user_id: str,
    provider_key: str,
    label: str = "",
    credentials: Mapping[str, str],
) -> LoyaltyAccount:
    """Start tracking a program. Empty credentials mean the balance is entered by hand."""
    provider = get_provider(provider_key)
    # The id is set up front because the encrypted login is bound to it.
    account = LoyaltyAccount(
        id=new_id(),
        user_id=user_id,
        provider=provider.key,
        label=(label.strip() or provider.program)[:MAX_LABEL_LENGTH],
        sync_status=SyncStatus.PENDING,
    )
    account.credentials_encrypted = _encrypt_credentials(vault, account, provider, credentials)
    db.add(account)
    db.commit()
    return account


def update_credentials(db: Session, vault: Vault, account: LoyaltyAccount, credentials: Mapping[str, str]) -> None:
    provider = get_provider(account.provider)
    _replace_login(db, account, _encrypt_credentials(vault, account, provider, credentials))


def remove_credentials(db: Session, account: LoyaltyAccount) -> None:
    _replace_login(db, account, None)


def _replace_login(db: Session, account: LoyaltyAccount, credentials_encrypted: bytes | None) -> None:
    account.credentials_encrypted = credentials_encrypted
    # Cookies kept by versions before 0.5 belong to the old login.
    account.session_state_encrypted = None
    account.sync_status = SyncStatus.PENDING
    account.sync_message = None
    db.commit()


def read_credentials(vault: Vault, account: LoyaltyAccount) -> dict[str, str] | None:
    if account.credentials_encrypted is None:
        return None
    return vault.decrypt_json(account.credentials_encrypted, context=_credentials_context(account))


def read_session_state(vault: Vault, account: LoyaltyAccount) -> dict | None:
    if account.session_state_encrypted is None:
        return None
    return vault.decrypt_json(account.session_state_encrypted, context=_session_context(account))


def save_session_state(vault: Vault, account: LoyaltyAccount, state: dict) -> None:
    account.session_state_encrypted = vault.encrypt_json(state, context=_session_context(account))


def _session_context(account: LoyaltyAccount) -> str:
    return f"loyalty_account:{account.user_id}:{account.id}:session"


def delete_account(db: Session, account: LoyaltyAccount) -> None:
    db.delete(account)
    db.commit()


def _credentials_context(account: LoyaltyAccount) -> str:
    return f"loyalty_account:{account.user_id}:{account.id}:credentials"


def _encrypt_credentials(
    vault: Vault, account: LoyaltyAccount, provider: Provider, credentials: Mapping[str, str]
) -> bytes | None:
    values = {}
    for field in provider.credential_fields:
        value = credentials.get(field.name, "")
        values[field.name] = value if field.secret else value.strip()
    filled = sum(1 for value in values.values() if value)
    if filled == 0:
        return None
    if filled < len(values):
        raise InvalidInput("Fill in every login field, or leave them all empty to enter balances by hand.")
    return vault.encrypt_json(values, context=_credentials_context(account))
