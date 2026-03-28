"""
common/crypto.py — Fernet-based password encryption for Account records.

When ACCOUNT_ENCRYPTION_KEY env var is set to a valid Fernet key, all account
passwords are encrypted at rest. In dev mode (no key), passwords are stored as-is.

Generate a key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import os
from typing import Optional

_KEY_RAW: Optional[str] = os.environ.get("ACCOUNT_ENCRYPTION_KEY")


def _get_fernet():
    """Return a Fernet instance from ACCOUNT_ENCRYPTION_KEY, or None if unset."""
    if not _KEY_RAW:
        return None
    try:
        from cryptography.fernet import Fernet
        key = _KEY_RAW.encode() if isinstance(_KEY_RAW, str) else _KEY_RAW
        return Fernet(key)
    except Exception as exc:
        raise RuntimeError(
            "ACCOUNT_ENCRYPTION_KEY is set but invalid. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt_password(plain: str) -> str:
    """Encrypt a plaintext password. Returns plaintext unchanged if no key is configured."""
    if not plain:
        return plain
    f = _get_fernet()
    if f is None:
        return plain  # dev mode
    return f.encrypt(plain.encode()).decode()


def decrypt_password(encrypted: Optional[str]) -> str:
    """Decrypt an encrypted password. Returns the value as-is in dev mode."""
    if not encrypted:
        return ""
    f = _get_fernet()
    if f is None:
        return encrypted  # dev mode
    try:
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        # Token invalid or corrupted — return empty to avoid exposing garbled data.
        return ""


def is_encryption_enabled() -> bool:
    """Return True if Fernet encryption is active."""
    return bool(_KEY_RAW)
