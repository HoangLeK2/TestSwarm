

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


# ── Process / server (main.py) ───────────────────────────────────────────────


def farm_config_path() -> str:
    p = (os.environ.get("FARM_CONFIG") or "config.yaml").strip()
    return p or "config.yaml"


def farm_reload_enabled() -> bool:
    return _truthy("FARM_RELOAD")


def farm_frontend_dist_override() -> Optional[str]:
    """Explicit SPA dist dir, or None to use default search in main."""
    raw = os.environ.get("FARM_FRONTEND_DIST", "").strip()
    return raw or None


def resolve_farm_frontend_dist(root_dir: Path) -> Optional[str]:
    """Prefer ``FARM_FRONTEND_DIST``, then ``<pkg>/front-end/dist``, then sibling ``../front-end/dist``."""
    raw = farm_frontend_dist_override()
    if raw:
        p = Path(raw).expanduser().resolve()
        return str(p) if p.is_dir() else None
    for c in (root_dir / "front-end" / "dist", root_dir.parent / "front-end" / "dist"):
        rp = c.resolve()
        if rp.is_dir():
            return str(rp)
    return None


def ngrok_enabled() -> bool:
    return _truthy("NGROK_ENABLED")


def ngrok_authtoken() -> str:
    return os.environ.get("NGROK_AUTHTOKEN", "").strip()


# ── JWT / auth (core/security, api/routes/auth) ──────────────────────────────


def secret_key_optional() -> Optional[str]:
    raw = (os.environ.get("SECRET_KEY") or "").strip()
    return raw or None


def jwt_algorithm_raw() -> str:
    return (os.environ.get("JWT_ALGORITHM") or "HS256").strip()


def access_expire_hours() -> int:
    return int(os.environ.get("ACCESS_EXPIRE_HOURS", "1"))


def refresh_expire_days() -> int:
    return int(os.environ.get("REFRESH_EXPIRE_DAYS", "30"))
