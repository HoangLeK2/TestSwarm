"""
common/crypto.py — Fernet-based password encryption for Account records.

When ACCOUNT_ENCRYPTION_KEY is a valid Fernet key, account passwords are
encrypted at rest. Production and staging fail closed when the key is absent or
invalid. Local development retains the legacy pass-through behind DEVICE_FARM_ENV.

Generate a key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import os
from typing import Optional

_KEY_RAW: Optional[str] = os.environ.get("ACCOUNT_ENCRYPTION_KEY")
_PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production", "staging"})


def _requires_encrypted_credentials() -> bool:
    return os.environ.get("DEVICE_FARM_ENV", "").strip().lower() in _PRODUCTION_ENVIRONMENTS


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
    """Encrypt a password, refusing plaintext storage in production-like environments."""
    if not plain:
        return plain
    f = _get_fernet()
    if f is None:
        if _requires_encrypted_credentials():
            raise RuntimeError(
                "Account credential encryption is unavailable in this environment"
            )
        return plain  # dev mode
    return f.encrypt(plain.encode()).decode()


def decrypt_password(encrypted: Optional[str]) -> str:
    """Decrypt a password, refusing plaintext fallback in production-like environments."""
    if not encrypted:
        return ""
    f = _get_fernet()
    if f is None:
        if _requires_encrypted_credentials():
            raise RuntimeError(
                "Account credential encryption is unavailable in this environment"
            )
        return encrypted  # dev mode
    try:
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        # Token invalid or corrupted — return empty to avoid exposing garbled data.
        return ""


def is_encryption_enabled() -> bool:
    """Return True only when the configured Fernet key is usable."""
    if not _KEY_RAW:
        return False
    try:
        return _get_fernet() is not None
    except RuntimeError:
        return False
