

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


def healing_enabled() -> bool:
    """Self-healing selectors: try alternative u2 selectors when primary fails.
    Env: DEVICE_FARM_HEALING_ENABLED=1 (default off)."""
    return _truthy("DEVICE_FARM_HEALING_ENABLED")


def device_farm_cv_concurrency() -> int:
    """
    Max concurrent OpenCV / Airtest CV ops (SSIM, template match).
    Env: DEVICE_FARM_CV_CONCURRENCY (default 4). Invalid or <1 → 1.
    """
    raw = (os.environ.get("DEVICE_FARM_CV_CONCURRENCY") or "").strip()
    if not raw:
        return 4
    try:
        return max(1, int(raw))
    except ValueError:
        return 4


def capture_pre_step_enabled() -> bool:
    """Enable pre-step screenshot capture in scenario runner.
    Env: CAPTURE_PRE_STEP=1 (default off)."""
    return _truthy("CAPTURE_PRE_STEP")


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


def password_min_length() -> int:
    raw = (os.environ.get("AUTH_PASSWORD_MIN_LENGTH") or "12").strip()
    try:
        return max(8, int(raw))
    except ValueError:
        return 12


def password_history_size() -> int:
    raw = (os.environ.get("AUTH_PASSWORD_HISTORY_SIZE") or "5").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def lockout_failed_threshold() -> int:
    raw = (os.environ.get("AUTH_LOCKOUT_FAILED_THRESHOLD") or "5").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def lockout_window_minutes() -> int:
    raw = (os.environ.get("AUTH_LOCKOUT_WINDOW_MINUTES") or "15").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 15


def lockout_duration_minutes() -> int:
    raw = (os.environ.get("AUTH_LOCKOUT_DURATION_MINUTES") or "30").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 30


# ── SMTP / organization invites ─────────────────────────────────────────────


def device_farm_frontend_url() -> str:
    return (
        os.environ.get("DEVICE_FARM_FRONTEND_URL", "").strip()
        or os.environ.get("FRONTEND_URL", "").strip()
        or "http://localhost:3000"
    )


def org_invite_expire_days() -> int:
    raw = (os.environ.get("ORG_INVITE_EXPIRE_DAYS") or "7").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 7


def smtp_host() -> str:
    return (os.environ.get("SMTP_HOST") or "").strip()


def smtp_port() -> int:
    raw = (os.environ.get("SMTP_PORT") or "587").strip()
    try:
        return int(raw)
    except ValueError:
        return 587


def smtp_user() -> str:
    return (os.environ.get("SMTP_USER") or "").strip()


def smtp_password() -> str:
    return (os.environ.get("SMTP_PASSWORD") or "").strip()


def smtp_from_address() -> str:
    return (
        os.environ.get("SMTP_FROM", "").strip()
        or os.environ.get("SMTP_USER", "").strip()
        or "noreply@device-farm.local"
    )


def smtp_use_tls() -> bool:
    return (os.environ.get("SMTP_USE_TLS", "1").strip().lower() not in {"0", "false", "no"})


def smtp_use_ssl() -> bool:
    return _truthy("SMTP_USE_SSL")
