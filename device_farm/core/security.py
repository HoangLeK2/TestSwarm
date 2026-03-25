
from __future__ import annotations

from core.env import jwt_algorithm_raw, secret_key_optional

_secret_key_cache: str | None = None
_algorithm_cache: str | None = None


def jwt_secret_key() -> str:
    global _secret_key_cache
    if _secret_key_cache is None:
        raw = secret_key_optional()
        if not raw:
            raise RuntimeError(
                "SECRET_KEY is not set. Set it in the environment or .env "
                "(see .env.example)."
            )
        _secret_key_cache = raw
    return _secret_key_cache


def jwt_algorithm() -> str:
    global _algorithm_cache
    if _algorithm_cache is None:
        _algorithm_cache = jwt_algorithm_raw()
    return _algorithm_cache


def clear_jwt_cache() -> None:
    global _secret_key_cache, _algorithm_cache
    _secret_key_cache = None
    _algorithm_cache = None
