from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account
from db.models.device_platform_session import DevicePlatformSession
from db.models.enums import AccountState, DevicePlatformSessionState
from services.account_state import (
    AccountStateError,
    AccountStateService,
    normalize_state,
)

log = logging.getLogger(__name__)

FACEBOOK_PLATFORM = "facebook"
FACEBOOK_APP_PACKAGE = "com.facebook.katana"

_SENSITIVE_EVIDENCE_KEYS = frozenset(
    {
        "password",
        "password_encrypted",
        "password_plain",
        "cookie",
        "cookies",
        "token",
        "access_token",
        "refresh_token",
        "totp",
        "totp_code",
        "totp_secret",
        "2fa_secret",
        "two_factor_secret",
        "screenshot",
        "screenshot_b64",
        "hierarchy",
        "hierarchy_xml",
        "xml",
    }
)
_MAX_EVIDENCE_STRING = 512
_MAX_EVIDENCE_ITEMS = 32


class DevicePlatformSessionError(Exception):
    code = "device_platform_session_error"


class DevicePlatformSessionConflict(DevicePlatformSessionError):
    code = "device_platform_session_conflict"


class InvalidDevicePlatformSessionTransition(DevicePlatformSessionError):
    code = "invalid_device_platform_session_transition"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _sync_account_state_for_session(
    db: AsyncSession,
    *,
    account_id: str,
    to: AccountState,
    reason: str,
) -> None:
    """Move the account between ``assigned`` and ``active`` with its session.

    ``active`` means "a verified session exists", nothing weaker — linking a
    device only gets an account as far as ``assigned`` (db.crud.account). So
    both directions run from the session: ``mark_active`` promotes, losing the
    session demotes. Operator-set and terminal states (``suspended``,
    ``banned``, ``retired``) are never touched here.
    """
    result = await db.execute(
        select(Account).where(Account.id == account_id).limit(1)
    )
    account = result.scalar_one_or_none()
    if account is None:
        return

    try:
        current = normalize_state(account.state or account.status)
    except ValueError as exc:
        log.warning("account %s session state sync skipped: %s", account_id, exc)
        return
    if current == to:
        return
    if to == AccountState.ASSIGNED and current != AccountState.ACTIVE:
        # Only a logged-in account falls back; a suspended or unassigned one
        # has a reason for its state that a dead session does not override.
        return

    svc = AccountStateService()
    try:
        if to == AccountState.ACTIVE and current == AccountState.UNASSIGNED:
            # A session on a device the link table never recorded still means
            # the account sits on that device — walk the ladder, don't skip it.
            await svc.transition(
                db,
                account_id,
                to=AccountState.ASSIGNED,
                reason=reason,
                actor="system",
                skip_row_lock=True,
            )
        await svc.transition(
            db,
            account_id,
            to=to,
            reason=reason,
            actor="system",
            skip_row_lock=True,
        )
    except AccountStateError as exc:
        log.warning(
            "account %s session state sync to %s failed from %s: %s",
            account_id,
            to.value,
            current.value,
            exc,
        )


async def _demote_account_for_lost_session(
    db: AsyncSession,
    account_id: str | None,
    reason: str,
) -> None:
    """Drop the account the session was holding back to ``assigned``."""
    if not account_id:
        return
    await _sync_account_state_for_session(
        db,
        account_id=str(account_id),
        to=AccountState.ASSIGNED,
        reason=reason,
    )


def sanitize_session_evidence(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, nested) in enumerate(value.items()):
            if index >= _MAX_EVIDENCE_ITEMS:
                out["truncated"] = True
                break
            raw_key = str(key)
            lowered = raw_key.lower()
            if lowered in _SENSITIVE_EVIDENCE_KEYS or any(
                needle in lowered for needle in ("password", "token", "cookie", "secret")
            ):
                continue
            cleaned = sanitize_session_evidence(nested, depth=depth + 1)
            if cleaned not in (None, "", {}, []):
                out[raw_key] = cleaned
        return out
    if isinstance(value, list):
        return [sanitize_session_evidence(item, depth=depth + 1) for item in value[:_MAX_EVIDENCE_ITEMS]]
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) > _MAX_EVIDENCE_STRING:
            return stripped[:_MAX_EVIDENCE_STRING] + "...[truncated]"
        return stripped
    return value


async def get_platform_session(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    platform: str = FACEBOOK_PLATFORM,
) -> DevicePlatformSession | None:
    result = await db.execute(
        select(DevicePlatformSession).where(
            DevicePlatformSession.org_id == org_id,
            DevicePlatformSession.device_id == device_id,
            DevicePlatformSession.platform == platform,
        )
    )
    return result.scalar_one_or_none()


async def list_platform_sessions(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
) -> list[DevicePlatformSession]:
    result = await db.execute(
        select(DevicePlatformSession)
        .where(
            DevicePlatformSession.org_id == org_id,
            DevicePlatformSession.device_id == device_id,
        )
        .order_by(DevicePlatformSession.platform)
    )
    return list(result.scalars().all())


async def get_or_create_platform_session(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    platform: str = FACEBOOK_PLATFORM,
    app_package: str = FACEBOOK_APP_PACKAGE,
) -> DevicePlatformSession:
    existing = await get_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    if existing is not None:
        return existing
    row = DevicePlatformSession(
        org_id=org_id,
        device_id=device_id,
        platform=platform,
        state=DevicePlatformSessionState.UNKNOWN.value,
        app_package=app_package,
        evidence={},
    )
    db.add(row)
    await db.flush()
    return row


def _check_expected_version(row: DevicePlatformSession, expected_version: int | None) -> None:
    if expected_version is not None and row.version != expected_version:
        raise DevicePlatformSessionConflict(
            f"session version conflict: expected {expected_version}, got {row.version}"
        )


def _bump(row: DevicePlatformSession) -> None:
    row.version = int(row.version or 0) + 1
    row.updated_at = _utcnow()


async def mark_login_required(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    platform: str = FACEBOOK_PLATFORM,
    reason: str,
    expected_account_id: str | None = None,
    expected_version: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> DevicePlatformSession:
    row = await get_or_create_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    _check_expected_version(row, expected_version)
    held_account_id = row.account_id
    row.account_id = None
    row.state = DevicePlatformSessionState.LOGIN_REQUIRED.value
    row.state_reason = reason
    row.invalidated_at = _utcnow()
    row.established_at = None
    row.establishment_method = None
    row.evidence = sanitize_session_evidence(
        {
            **(evidence or {}),
            "expected_account_id": expected_account_id,
        }
    )
    _bump(row)
    await _demote_account_for_lost_session(db, held_account_id, reason)
    await db.flush()
    return row


async def mark_active(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str,
    platform: str = FACEBOOK_PLATFORM,
    establishment_method: str,
    reason: str,
    expected_version: int | None = None,
    app_package: str = FACEBOOK_APP_PACKAGE,
    app_version: str | None = None,
    display_name_observed: str | None = None,
    login_attempt_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> DevicePlatformSession:
    if not account_id or not establishment_method:
        raise InvalidDevicePlatformSessionTransition("active session requires account and establishment method")
    row = await get_or_create_platform_session(
        db, org_id=org_id, device_id=device_id, platform=platform, app_package=app_package
    )
    _check_expected_version(row, expected_version)
    now = _utcnow()
    row.account_id = account_id
    row.state = DevicePlatformSessionState.ACTIVE.value
    row.state_reason = reason
    row.established_at = now
    row.last_ready_at = now
    row.last_checked_at = now
    row.invalidated_at = None
    row.login_attempt_id = login_attempt_id
    row.establishment_method = establishment_method
    row.app_package = app_package
    row.app_version = app_version
    row.display_name_observed = display_name_observed
    row.evidence = sanitize_session_evidence(evidence or {})
    _bump(row)
    await _sync_account_state_for_session(
        db,
        account_id=account_id,
        to=AccountState.ACTIVE,
        reason=reason,
    )
    await db.flush()
    return row


async def mark_logging_in(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str,
    platform: str = FACEBOOK_PLATFORM,
    reason: str,
    login_attempt_id: str,
    evidence: dict[str, Any] | None = None,
) -> DevicePlatformSession:
    row = await get_or_create_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    row.account_id = account_id
    row.state = DevicePlatformSessionState.LOGGING_IN.value
    row.state_reason = reason
    row.login_attempt_id = login_attempt_id
    row.evidence = sanitize_session_evidence(evidence or {})
    _bump(row)
    await db.flush()
    return row


async def mark_readiness_observed(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    state: DevicePlatformSessionState,
    reason: str,
    account_id: str | None = None,
    platform: str = FACEBOOK_PLATFORM,
    evidence: dict[str, Any] | None = None,
) -> DevicePlatformSession:
    row = await get_or_create_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    now = _utcnow()
    if account_id is not None:
        row.account_id = account_id
    row.state = state.value
    row.state_reason = reason
    row.last_checked_at = now
    if state == DevicePlatformSessionState.ACTIVE:
        row.last_ready_at = now
        row.invalidated_at = None
        if row.account_id:
            await _sync_account_state_for_session(
                db,
                account_id=str(row.account_id),
                to=AccountState.ACTIVE,
                reason=reason,
            )
    elif state in {
        DevicePlatformSessionState.LOGGED_OUT,
        DevicePlatformSessionState.LOGIN_REQUIRED,
        DevicePlatformSessionState.CHECKPOINT,
        DevicePlatformSessionState.EXPIRED,
        DevicePlatformSessionState.FAILED,
    }:
        row.last_ready_at = None
        row.invalidated_at = now
        await _demote_account_for_lost_session(db, row.account_id, reason)
    row.evidence = sanitize_session_evidence(evidence or {})
    _bump(row)
    await db.flush()
    return row


async def record_display_name_observed(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    display_name: str,
    platform: str = FACEBOOK_PLATFORM,
) -> DevicePlatformSession | None:
    """Store the name the account's own profile page actually shows.

    Only ever an observation: it does not touch state, account or evidence, so a
    scenario that reads the profile cannot change who the session belongs to.
    Nothing is created — a name with no session behind it is an observation
    about a device nobody has claimed.
    """
    name = str(display_name or "").strip()[:255]
    if not name:
        return None
    row = await get_platform_session(
        db, org_id=org_id, device_id=device_id, platform=platform
    )
    if row is None or row.display_name_observed == name:
        return row
    row.display_name_observed = name
    _bump(row)
    await db.flush()
    return row


async def observed_display_names(
    db: AsyncSession,
    *,
    org_id: str,
    account_ids: Sequence[str],
    platform: str = FACEBOOK_PLATFORM,
) -> dict[str, str]:
    """Name each account's own profile last showed, keyed by account, in one query.

    An account can sit on more than one phone; the most recently touched session
    that still owns it wins. Read-only — the account row keeps whatever name the
    operator typed, and this stays an observation next to it.
    """
    ids = [str(a) for a in account_ids if a]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                DevicePlatformSession.account_id,
                DevicePlatformSession.display_name_observed,
            )
            .where(
                DevicePlatformSession.org_id == org_id,
                DevicePlatformSession.platform == platform,
                DevicePlatformSession.account_id.in_(ids),
                DevicePlatformSession.display_name_observed.is_not(None),
            )
            .order_by(DevicePlatformSession.updated_at.asc())
        )
    ).all()
    # Ascending order means a later row overwrites an earlier one, so the map
    # ends up holding the newest observation per account.
    return {account_id: name for account_id, name in rows if name}


async def invalidate_platform_session(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    platform: str = FACEBOOK_PLATFORM,
    reason: str,
    expected_version: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> DevicePlatformSession:
    row = await get_or_create_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    _check_expected_version(row, expected_version)
    held_account_id = row.account_id
    row.account_id = None
    row.state = DevicePlatformSessionState.LOGIN_REQUIRED.value
    row.state_reason = reason
    row.invalidated_at = _utcnow()
    row.established_at = None
    row.last_ready_at = None
    row.establishment_method = None
    row.evidence = sanitize_session_evidence(evidence or {})
    _bump(row)
    await _demote_account_for_lost_session(db, held_account_id, reason)
    await db.flush()
    return row


async def mark_login_required_for_primary_change(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str,
    platform: str = FACEBOOK_PLATFORM,
) -> DevicePlatformSession:
    current = await get_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    if (
        current is not None
        and current.state == DevicePlatformSessionState.ACTIVE.value
        and current.account_id == account_id
    ):
        return current
    return await mark_login_required(
        db,
        org_id=org_id,
        device_id=device_id,
        platform=platform,
        reason="primary_account_changed",
        expected_account_id=account_id,
    )


async def invalidate_if_account_holds_provenance(
    db: AsyncSession,
    *,
    org_id: str,
    device_id: str,
    account_id: str,
    platform: str = FACEBOOK_PLATFORM,
    reason: str = "provenance_account_unassigned",
) -> DevicePlatformSession | None:
    current = await get_platform_session(db, org_id=org_id, device_id=device_id, platform=platform)
    if current is None or current.account_id != account_id:
        return current
    return await invalidate_platform_session(
        db,
        org_id=org_id,
        device_id=device_id,
        platform=platform,
        reason=reason,
        evidence={"removed_account_id": account_id},
    )
