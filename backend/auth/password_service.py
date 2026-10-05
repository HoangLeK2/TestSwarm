"""Password hashing and timing-safe verification."""
from __future__ import annotations

from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

# Constant-time path when user record is missing (anti-enumeration).
_DUMMY_HASH = _pwd.hash("timing-safe-dummy-password-for-unknown-users")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def verify_with_timing_safe(plain: str, user_hash: str | None) -> bool:
    """Verify against user hash, or dummy hash when user does not exist."""
    target = user_hash if user_hash else _DUMMY_HASH
    try:
        ok = _pwd.verify(plain, target)
    except Exception:
        ok = False
    return ok and user_hash is not None
