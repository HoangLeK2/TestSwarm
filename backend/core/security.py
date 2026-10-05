
from __future__ import annotations

from core.env import secret_key_optional

_secret_key_cache: str | None = None
_algorithm_cache: str | None = None


def jwt_secret_key() -> str:
    """Return the active signing secret (multi-version aware)."""
    global _secret_key_cache
    if _secret_key_cache is None:
        from auth.secret_versioning import reload_jwt_secrets, signing_material

        reload_jwt_secrets()
        _secret_key_cache = signing_material()[1]
    return _secret_key_cache


def jwt_algorithm() -> str:
    global _algorithm_cache
    if _algorithm_cache is None:
        from core.env import jwt_algorithm_raw

        _algorithm_cache = jwt_algorithm_raw()
    return _algorithm_cache


def clear_jwt_cache() -> None:
    global _secret_key_cache, _algorithm_cache
    _secret_key_cache = None
    _algorithm_cache = None
    try:
        from auth import secret_versioning

        secret_versioning.reload_jwt_secrets()
    except Exception:
        pass
