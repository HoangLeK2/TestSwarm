"""JWT multi-version secret loading and verification (DF-T-01-006)."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from core.env import jwt_secret_overlap_hours

log = logging.getLogger(__name__)


class JwtKeyRevokedError(Exception):
    code = "TOKEN_EXPIRED_KEY_REVOKED"


@dataclass(frozen=True)
class JwtKeyMaterial:
    kid: str
    secret: str
    revoked_after: float | None = None


_store: list[JwtKeyMaterial] | None = None
_active_kid: str | None = None


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _load_store() -> tuple[list[JwtKeyMaterial], str]:
    active_kid = _env("JWT_ACTIVE_KID") or "v1"
    active_secret = _env("SECRET_KEY") or _env(f"JWT_SECRET_{active_kid.upper()}")
    if not active_secret:
        raise RuntimeError("SECRET_KEY is not set")

    keys: list[JwtKeyMaterial] = [
        JwtKeyMaterial(kid=active_kid, secret=active_secret),
    ]

    previous_kid = _env("JWT_SECRET_PREVIOUS_KID")
    previous_secret = _env("JWT_SECRET_PREVIOUS")
    if previous_kid and previous_secret:
        rotated_at_raw = _env("JWT_SECRET_PREVIOUS_ROTATED_AT")
        overlap = jwt_secret_overlap_hours() * 3600
        revoked_after = None
        if rotated_at_raw:
            try:
                revoked_after = float(rotated_at_raw) + overlap
            except ValueError:
                revoked_after = None
        keys.append(
            JwtKeyMaterial(
                kid=previous_kid,
                secret=previous_secret,
                revoked_after=revoked_after,
            )
        )

    for name, value in os.environ.items():
        if not name.startswith("JWT_SECRET_V") or name.endswith("_REVOKED_AT"):
            continue
        kid = name.removeprefix("JWT_SECRET_").lower()
        if kid == active_kid.lower() or (previous_kid and kid == previous_kid.lower()):
            continue
        if value.strip():
            keys.append(JwtKeyMaterial(kid=kid, secret=value.strip()))

    return keys, active_kid


def reload_jwt_secrets() -> None:
    global _store, _active_kid
    _store, _active_kid = _load_store()
    log.info("JWT secret store loaded active_kid=%s versions=%d", _active_kid, len(_store))


def active_kid() -> str:
    if _active_kid is None:
        reload_jwt_secrets()
    return _active_kid or "v1"


def signing_material() -> tuple[str, str]:
    if _store is None:
        reload_jwt_secrets()
    kid = active_kid()
    for item in _store or []:
        if item.kid == kid:
            return item.kid, item.secret
    first = (_store or [])[0]
    return first.kid, first.secret


def verify_material_for_kid(kid: str | None) -> JwtKeyMaterial:
    if _store is None:
        reload_jwt_secrets()
    lookup = (kid or active_kid()).strip() or active_kid()
    for item in _store or []:
        if item.kid == lookup:
            if item.revoked_after is not None and time.time() > item.revoked_after:
                raise JwtKeyRevokedError(f"JWT kid {lookup} revoked")
            return item
    raise JwtKeyRevokedError(f"unknown JWT kid {lookup}")


def all_verify_materials() -> list[JwtKeyMaterial]:
    if _store is None:
        reload_jwt_secrets()
    now = time.time()
    out: list[JwtKeyMaterial] = []
    for item in _store or []:
        if item.revoked_after is not None and now > item.revoked_after:
            continue
        out.append(item)
    return out


def secret_age_days() -> dict[str, float]:
    rotated_at_raw = _env("JWT_SECRET_PREVIOUS_ROTATED_AT")
    if not rotated_at_raw:
        return {active_kid(): 0.0}
    try:
        age = max(0.0, (time.time() - float(rotated_at_raw)) / 86400.0)
    except ValueError:
        age = 0.0
    return {active_kid(): age}
