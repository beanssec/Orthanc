from __future__ import annotations
import base64
import json
from argon2.low_level import hash_secret_raw, Type
from cryptography.fernet import Fernet


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from password using Argon2id."""
    raw_key = hash_secret_raw(
        secret=password.encode(),
        salt=salt,
        time_cost=2,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        type=Type.ID,
    )
    return base64.urlsafe_b64encode(raw_key)


def encrypt_credentials(data: dict, password: str, salt: bytes) -> tuple[bytes, bytes]:
    """Encrypt a dict with Fernet using Argon2-derived key.

    Returns (encrypted_blob, nonce) where nonce is the salt used for key derivation.
    """
    key = derive_key(password, salt)
    f = Fernet(key)
    plaintext = json.dumps(data).encode()
    encrypted_blob = f.encrypt(plaintext)
    return encrypted_blob, salt


def decrypt_credentials(encrypted_blob: bytes, nonce: bytes, password: str) -> dict:
    """Decrypt an encrypted blob using Argon2-derived key."""
    key = derive_key(password, nonce)
    f = Fernet(key)
    plaintext = f.decrypt(encrypted_blob)
    return json.loads(plaintext.decode())
