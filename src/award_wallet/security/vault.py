"""Encryption for secrets the app must read back later, such as program logins.

Ciphertexts are AES-256-GCM, laid out as:

    version (1 byte) | key id length (1 byte) | key id | nonce (12 bytes) | ciphertext + tag

Each one is bound to a context string naming its owner (for example a user and an account),
so a ciphertext copied onto another row fails to decrypt instead of leaking someone's login.
"""

import base64
import binascii
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = 1
_NONCE_SIZE = 12


class VaultError(Exception):
    """A ciphertext could not be decrypted."""


def generate_key() -> str:
    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()


class Vault:
    def __init__(self, keys: dict[str, bytes], primary_key_id: str) -> None:
        if primary_key_id not in keys:
            raise ValueError(f"Primary key {primary_key_id!r} is not among the keys")
        for key_id, key in keys.items():
            if not key_id or len(key_id.encode()) > 255:
                raise ValueError("Key ids must be 1 to 255 bytes long")
            if len(key) != 32:
                raise ValueError(f"Key {key_id!r} must be 32 bytes, got {len(key)}")
        self._ciphers = {key_id: AESGCM(key) for key_id, key in keys.items()}
        self._primary_key_id = primary_key_id

    @classmethod
    def from_config(cls, value: str) -> "Vault":
        """Build a vault from AW_ENCRYPTION_KEYS ("key_id:base64key,older_id:base64key")."""
        keys: dict[str, bytes] = {}
        for entry in filter(None, (part.strip() for part in value.split(","))):
            key_id, sep, encoded = entry.partition(":")
            if not sep:
                raise ValueError("Each encryption key must look like key_id:base64key")
            try:
                keys[key_id] = base64.urlsafe_b64decode(encoded)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(f"Encryption key {key_id!r} is not valid base64") from exc
        if not keys:
            raise ValueError("No encryption keys configured")
        return cls(keys, primary_key_id=next(iter(keys)))

    def encrypt(self, plaintext: bytes, *, context: str) -> bytes:
        key_id = self._primary_key_id.encode()
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = self._ciphers[self._primary_key_id].encrypt(nonce, plaintext, context.encode())
        return bytes([_VERSION, len(key_id)]) + key_id + nonce + ciphertext

    def decrypt(self, blob: bytes, *, context: str) -> bytes:
        if len(blob) < 2 or blob[0] != _VERSION:
            raise VaultError("Unrecognized ciphertext format")
        id_end = 2 + blob[1]
        try:
            key_id = blob[2:id_end].decode()
        except UnicodeDecodeError as exc:
            raise VaultError("Unrecognized ciphertext format") from exc
        cipher = self._ciphers.get(key_id)
        if cipher is None:
            raise VaultError(f"Encrypted with key {key_id!r}, which is not in AW_ENCRYPTION_KEYS")
        nonce, ciphertext = blob[id_end : id_end + _NONCE_SIZE], blob[id_end + _NONCE_SIZE :]
        try:
            return cipher.decrypt(nonce, ciphertext, context.encode())
        except (InvalidTag, ValueError) as exc:
            raise VaultError("Ciphertext failed authentication") from exc

    def encrypt_json(self, data: Any, *, context: str) -> bytes:
        return self.encrypt(json.dumps(data).encode(), context=context)

    def decrypt_json(self, blob: bytes, *, context: str) -> Any:
        return json.loads(self.decrypt(blob, context=context))
