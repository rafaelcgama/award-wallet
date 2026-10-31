import base64

import pytest

from award_wallet.security.vault import Vault, VaultError, generate_key


def make_vault(*entries: tuple[str, str]) -> Vault:
    return Vault.from_config(",".join(f"{key_id}:{key}" for key_id, key in entries))


def test_round_trip():
    vault = make_vault(("k1", generate_key()))
    blob = vault.encrypt_json({"username": "rafael", "password": "s3cret"}, context="account:1")
    assert b"s3cret" not in blob
    assert vault.decrypt_json(blob, context="account:1") == {"username": "rafael", "password": "s3cret"}


def test_ciphertext_is_bound_to_its_context():
    vault = make_vault(("k1", generate_key()))
    blob = vault.encrypt(b"secret", context="account:1")
    with pytest.raises(VaultError):
        vault.decrypt(blob, context="account:2")


def test_tampering_is_detected():
    vault = make_vault(("k1", generate_key()))
    blob = bytearray(vault.encrypt(b"secret", context="ctx"))
    blob[-1] ^= 1
    with pytest.raises(VaultError):
        vault.decrypt(bytes(blob), context="ctx")


def test_rotation_keeps_old_data_readable():
    old_key, new_key = generate_key(), generate_key()
    old_blob = make_vault(("old", old_key)).encrypt(b"legacy", context="ctx")

    rotated = make_vault(("new", new_key), ("old", old_key))
    assert rotated.decrypt(old_blob, context="ctx") == b"legacy"

    new_blob = rotated.encrypt(b"fresh", context="ctx")
    with pytest.raises(VaultError, match="not in AW_ENCRYPTION_KEYS"):
        make_vault(("old", old_key)).decrypt(new_blob, context="ctx")


def test_rejects_bad_configuration():
    with pytest.raises(ValueError):
        Vault.from_config("")
    with pytest.raises(ValueError):
        Vault.from_config("no-separator")
    with pytest.raises(ValueError):
        Vault.from_config("k1:" + base64.urlsafe_b64encode(b"too short").decode())


def test_rejects_garbage():
    vault = make_vault(("k1", generate_key()))
    for blob in (b"", b"\x01", b"\x02abc", b"\x01\x05k1"):
        with pytest.raises(VaultError):
            vault.decrypt(blob, context="ctx")
