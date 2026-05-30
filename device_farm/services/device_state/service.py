"""Device FSM apply engine + state store (DF-T-02-002)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device_state import ensure_device_state, get_device_state
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot, DeviceStateTransition
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from db.models.tenant_settings import DEFAULT_DEAD_THRESHOLD_SEC, TenantSettings
from services.activity_logger import log_activity
from services.device_state.events import (
    DeviceDeadEvent,
    DeviceRevivedEvent,
    DeviceStateChangedEvent,
    SessionLostDeviceEvent,
    publish_device_dead,
    publish_device_revived,
    publish_device_state_changed,
    publish_session_lost_device,
)
from services.device_state.exceptions import DeviceNotAvailableError, IllegalDeviceTransitionError
from services.device_state.fsm import normalize_state, resolve_transition
from web.metrics import (
    device_dead_count,
    fsm_event_dedup_count,
    fsm_illegal_transition_count,
    fsm_transition_count,
)

log = logging.getLogger(__name__)

RECONNECTING_TTL_SECONDS = int(os.environ.get("DEVICE_FSM_RECONNECTING_TTL_SECONDS", "300"))
DEAD_DETECTION_SCAN_LIMIT = int(os.environ.get("DEVICE_DEAD_DETECTION_SCAN_LIMIT", "500"))
DEAD_DETECTION_INTERVAL_SEC = int(os.environ.get("DEVICE_DEAD_DETECTION_INTERVAL_SEC", "60"))


@dataclass(frozen=True, slots=True)
class ReconnectingCandidate:
    snapshot: DeviceFsmSnapshot
    org_id: str
    serial: str
    user_id: Optional[str]


class ApplyOutcome(str, Enum):
    APPLIED = "applied"
    DEDUPED = "deduped"
    IGNORED = "ignored"
    ILLEGAL = "illegal"
    NO_OP = "no_op"


@dataclass(frozen=True, slots=True)
class ApplyResult:
    outcome: ApplyOutcome
    state: DeviceFsmState
    from_state: Optional[DeviceFsmState] = None
    to_state: Optional[DeviceFsmState] = None


def _event_id_order(a: str, b: str) -> int | None:
    """Return -1 if a<b, 0 if equal, 1 if a>b, or None if not both numeric."""
    if a == b:
        return 0
    try:
        ia, ib = int(a), int(b)
    except ValueError:
        return None
    return -1 if ia < ib else 1


class DeviceStateService:
    """Apply FSM transitions on ``device_states`` with audit + idempotency."""

    async def apply_event(
        self,
        db: AsyncSession,
        device_id: str,
        *,
        event: str,
        source: str,
        event_id: Optional[str] = None,
        session_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        skip_row_lock: bool = False,
    ) -> ApplyResult:
        if skip_row_lock:
            row = await ensure_device_state(db, device_id)
        else:
            row = await self._load_for_update(db, device_id)

        current = normalize_state(row.state)

        if event_id and row.last_event_id:
            order = _event_id_order(event_id, row.last_event_id)
            if order == 0:
                try:
                    fsm_event_dedup_count.inc()
                except Exception:
                    pass
                return ApplyResult(outcome=ApplyOutcome.DEDUPED, state=current)
            if order is not None and order < 0:
                log.info(
                    "stale_device_fsm_event device=%s event=%s event_id=%s last=%s",
                    device_id,
                    event,
                    event_id,
                    row.last_event_id,
                )
                return ApplyResult(outcome=ApplyOutcome.IGNORED, state=current)

        resolution = resolve_transition(current, event, source=source)

        if resolution == "IGNORE":
            if event == DeviceFsmEvent.BUSY.value and source == "agent":
                log.info(
                    "agent_busy_event_ignored device=%s state=%s event_id=%s",
                    device_id,
                    current.value,
                    event_id,
                )
            if event_id:
                row.last_event_id = event_id
                row.updated_at = datetime.now(timezone.utc)
                await db.flush()
            return ApplyResult(outcome=ApplyOutcome.IGNORED, state=current)

        if resolution == "ILLEGAL":
            log.warning(
                "illegal_transition device=%s from=%s event=%s source=%s",
                device_id,
                current.value,
                event,
                source,
            )
            try:
                fsm_illegal_transition_count.inc()
            except Exception:
                pass
            return ApplyResult(outcome=ApplyOutcome.ILLEGAL, state=current)

        if resolution == "NO_OP":
            if event_id:
                row.last_event_id = event_id
                row.updated_at = datetime.now(timezone.utc)
                await db.flush()
            return ApplyResult(outcome=ApplyOutcome.NO_OP, state=current)

        next_state = normalize_state(resolution)
        if next_state == current:
            return ApplyResult(outcome=ApplyOutcome.NO_OP, state=current)

        return await self._commit_transition(
            db,
            row,
            from_state=current,
            to_state=next_state,
            event=event,
            source=source,
            event_id=event_id,
            session_id=session_id,
            payload=payload,
        )

    async def claim(
        self,
        db: AsyncSession,
        device_id: str,
        session_id: str,
        *,
        event_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> ApplyResult:
        row = await self._load_for_update(db, device_id)
        current = normalize_state(row.state)
        if current != DeviceFsmState.ONLINE:
            if (
                current == DeviceFsmState.BUSY
                and event_id
                and row.last_event_id == event_id
            ):
                return ApplyResult(
                    outcome=ApplyOutcome.DEDUPED,
                    state=current,
                    from_state=current,
                    to_state=current,
                )
            raise DeviceNotAvailableError(
                f"device {device_id} not available for claim (state={current.value})"
            )
        body = dict(payload or {})
        body["session_id"] = session_id
        result = await self.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.SESSION_CLAIM.value,
            source="claim",
            event_id=event_id,
            session_id=session_id,
            payload=body,
            skip_row_lock=True,
        )
        if result.outcome == ApplyOutcome.ILLEGAL:
            raise IllegalDeviceTransitionError(
                f"cannot claim device {device_id} from state {current.value}"
            )
        return result

    async def release(
        self,
        db: AsyncSession,
        device_id: str,
        session_id: str,
        *,
        event_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> ApplyResult:
        row = await self._load_for_update(db, device_id)
        current = normalize_state(row.state)
        if current != DeviceFsmState.BUSY:
            raise IllegalDeviceTransitionError(
                f"device {device_id} is not BUSY (state={current.value})"
            )
        if row.session_id and row.session_id != session_id:
            raise IllegalDeviceTransitionError(
                f"device {device_id} held by session {row.session_id}, not {session_id}"
            )
        body = dict(payload or {})
        body["session_id"] = session_id
        return await self.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.SESSION_RELEASED.value,
            source="claim",
            event_id=event_id,
            session_id=None,
            payload=body,
            skip_row_lock=True,
        )

    async def mark_dead_reconnect_timeout(
        self,
        db: AsyncSession,
        device_id: str,
        *,
        reason: str = "reconnect_timeout",
        owner_user_id: Optional[str] = None,
        device_serial: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> ApplyResult:
        """Transition RECONNECTING → DEAD after reconnect window exceeded (DF-T-02-005)."""
        row = await self._load_for_update(db, device_id)
        current = normalize_state(row.state)
        if current != DeviceFsmState.RECONNECTING:
            return ApplyResult(outcome=ApplyOutcome.IGNORED, state=current)

        entered_reconnect_at = row.reconnecting_since
        last_known_state = current.value
        session_id = row.session_id

        payload: dict[str, Any] = {
            "reason": reason,
            "last_known_state": last_known_state,
            "entered_reconnect_at": (
                entered_reconnect_at.isoformat() if entered_reconnect_at else None
            ),
            "owner_user_id": owner_user_id,
        }
        result = await self.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.DEAD.value,
            source="system",
            event_id=event_id,
            payload=payload,
            skip_row_lock=True,
        )
        if result.outcome != ApplyOutcome.APPLIED:
            return result

        publish_device_dead(
            DeviceDeadEvent(
                device_id=device_id,
                reason=reason,
                last_known_state=last_known_state,
                entered_reconnect_at=payload["entered_reconnect_at"],
                session_id=session_id,
            )
        )
        try:
            device_dead_count.labels(reason=reason).inc()
        except Exception:
            pass
        await log_activity(
            db,
            action="device.dead",
            entity_type="device",
            entity_id=device_id,
            device_serial=device_serial,
            details=payload,
        )
        return result

    async def revive(
        self,
        db: AsyncSession,
        device_id: str,
        *,
        actor: str,
        device_serial: Optional[str] = None,
    ) -> ApplyResult:
        """Admin revive: DEAD → CONNECTING (DF-T-02-005)."""
        row = await self._load_for_update(db, device_id)
        current = normalize_state(row.state)
        if current != DeviceFsmState.DEAD:
            raise IllegalDeviceTransitionError(
                f"device {device_id} is not DEAD (state={current.value})"
            )
        event_id = f"revive-{device_id}-{int(datetime.now(timezone.utc).timestamp())}"
        result = await self.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.REVIVED.value,
            source="admin",
            event_id=event_id,
            payload={"actor": actor},
            skip_row_lock=True,
        )
        if result.outcome != ApplyOutcome.APPLIED:
            return result

        publish_device_revived(
            DeviceRevivedEvent(device_id=device_id, actor=actor)
        )
        await log_activity(
            db,
            action="device.revived",
            entity_type="device",
            entity_id=device_id,
            device_serial=device_serial,
            user_id=actor if actor != "system" else None,
            details={"actor": actor},
        )
        return result

    async def get_state(self, db: AsyncSession, device_id: str) -> DeviceFsmState:
        row = await get_device_state(db, device_id)
        if row is None:
            return DeviceFsmState.UNKNOWN
        return normalize_state(row.state)

    async def _load_for_update(
        self, db: AsyncSession, device_id: str
    ) -> DeviceFsmSnapshot:
        result = await db.execute(
            select(DeviceFsmSnapshot)
            .where(DeviceFsmSnapshot.device_id == device_id)
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            return await ensure_device_state(db, device_id)
        return row

    async def _commit_transition(
        self,
        db: AsyncSession,
        row: DeviceFsmSnapshot,
        *,
        from_state: DeviceFsmState,
        to_state: DeviceFsmState,
        event: str,
        source: str,
        event_id: Optional[str],
        session_id: Optional[str],
        payload: Optional[dict[str, Any]],
    ) -> ApplyResult:
        now = datetime.now(timezone.utc)
        merged_payload = dict(payload or {})
        row.state = to_state.value
        row.updated_at = now
        if event_id:
            row.last_event_id = event_id

        if to_state == DeviceFsmState.BUSY:
            row.session_id = session_id
        elif to_state == DeviceFsmState.ONLINE and from_state == DeviceFsmState.BUSY:
            row.session_id = None

        if to_state == DeviceFsmState.RECONNECTING:
            row.reconnecting_since = now
        elif from_state == DeviceFsmState.RECONNECTING and to_state == DeviceFsmState.ONLINE:
            row.reconnecting_since = None
        elif to_state == DeviceFsmState.DEAD:
            held_session = row.session_id
            if held_session:
                owner_user_id = merged_payload.get("owner_user_id")
                if isinstance(owner_user_id, str):
                    owner_user_id = owner_user_id.strip() or None
                else:
                    owner_user_id = None
                if owner_user_id is None:
                    owner_user_id = await self._resolve_device_owner(db, row.device_id)
                await self._force_release_session(
                    db,
                    row,
                    session_id=held_session,
                    reason="device_lost",
                    owner_user_id=owner_user_id,
                    device_fsm_state=from_state.value,
                )
            row.reconnecting_since = None
            row.session_id = None
        elif to_state == DeviceFsmState.CONNECTING and from_state == DeviceFsmState.DEAD:
            row.reconnecting_since = None

        if session_id:
            merged_payload.setdefault("session_id", session_id)

        db.add(
            DeviceStateTransition(
                device_id=row.device_id,
                from_state=from_state.value,
                to_state=to_state.value,
                event=event,
                source=source,
                event_id=event_id,
                timestamp=now,
                payload=merged_payload or None,
            )
        )
        await db.flush()

        publish_device_state_changed(
            DeviceStateChangedEvent(
                device_id=row.device_id,
                from_state=from_state.value,
                to_state=to_state.value,
                event=event,
                source=source,
                event_id=event_id,
                session_id=session_id,
                payload=merged_payload or None,
            )
        )
        try:
            fsm_transition_count.labels(
                from_state=from_state.value,
                to_state=to_state.value,
            ).inc()
        except Exception:
            pass

        log.info(
            "device_fsm_transition device=%s %s->%s event=%s source=%s",
            row.device_id,
            from_state.value,
            to_state.value,
            event,
            source,
        )
        return ApplyResult(
            outcome=ApplyOutcome.APPLIED,
            state=to_state,
            from_state=from_state,
            to_state=to_state,
        )

    async def _force_release_session(
        self,
        db: AsyncSession,
        row: DeviceFsmSnapshot,
        *,
        session_id: str,
        reason: str,
        owner_user_id: Optional[str],
        device_fsm_state: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        payload = {"session_id": session_id, "reason": reason}
        db.add(
            DeviceStateTransition(
                device_id=row.device_id,
                from_state=device_fsm_state,
                to_state=device_fsm_state,
                event=DeviceFsmEvent.SESSION_LOST.value,
                source="system",
                timestamp=now,
                payload=payload,
            )
        )
        row.session_id = None
        await db.flush()
        publish_session_lost_device(
            SessionLostDeviceEvent(
                device_id=row.device_id,
                session_id=session_id,
                reason=reason,
                owner_user_id=owner_user_id,
            )
        )
        await self._notify_session_lost(owner_user_id, row.device_id, session_id, reason)

    async def _notify_session_lost(
        self,
        owner_user_id: Optional[str],
        device_id: str,
        session_id: str,
        reason: str,
    ) -> None:
        if not owner_user_id:
            return
        try:
            from services.notification_service import NotificationService

            svc = NotificationService()
            await svc.notify(
                event=DeviceFsmEvent.SESSION_LOST.value,
                title="Device session lost",
                body=f"Session {session_id} ended: {reason}",
                data={
                    "device_id": device_id,
                    "session_id": session_id,
                    "reason": reason,
                },
                user_id=owner_user_id,
            )
        except Exception as exc:
            log.debug("session.lost_device notification skipped: %s", exc)

    async def _resolve_device_owner(
        self, db: AsyncSession, device_id: str
    ) -> Optional[str]:
        result = await db.execute(
            select(Device.user_id).where(Device.id == device_id)
        )
        return result.scalar_one_or_none()


async def list_reconnecting_candidates(
    db: AsyncSession,
    *,
    limit: int | None = None,
) -> list[ReconnectingCandidate]:
    """RECONNECTING devices with org context (no threshold filter)."""
    cap = limit if limit is not None else DEAD_DETECTION_SCAN_LIMIT
    result = await db.execute(
        select(DeviceFsmSnapshot, Device)
        .join(Device, Device.id == DeviceFsmSnapshot.device_id)
        .where(DeviceFsmSnapshot.state == DeviceFsmState.RECONNECTING.value)
        .where(DeviceFsmSnapshot.reconnecting_since.is_not(None))
        .order_by(DeviceFsmSnapshot.reconnecting_since.asc())
        .limit(cap)
    )
    return _rows_to_reconnecting_candidates(result.all())


def _rows_to_reconnecting_candidates(
    rows: list[tuple[DeviceFsmSnapshot, Device]],
) -> list[ReconnectingCandidate]:
    return [
        ReconnectingCandidate(
            snapshot=snap,
            org_id=device.org_id,
            serial=device.serial,
            user_id=device.user_id,
        )
        for snap, device in rows
    ]


async def list_stale_reconnecting_candidates(
    db: AsyncSession,
    *,
    limit: int | None = None,
) -> list[ReconnectingCandidate]:
    """RECONNECTING devices past per-org dead threshold (oldest stale first).

    PostgreSQL pushes threshold into SQL to avoid head-of-line blocking when
    slow-threshold tenants occupy the oldest RECONNECTING slots. Other dialects
    (SQLite tests) scan all RECONNECTING rows then filter in Python.
    """
    cap = limit if limit is not None else DEAD_DETECTION_SCAN_LIMIT
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return await _list_stale_reconnecting_postgresql(db, limit=cap)
    return await _list_stale_reconnecting_fallback(db, limit=cap)


async def _list_stale_reconnecting_postgresql(
    db: AsyncSession,
    *,
    limit: int,
) -> list[ReconnectingCandidate]:
    threshold_sec = func.coalesce(
        TenantSettings.dead_threshold_sec, DEFAULT_DEAD_THRESHOLD_SEC
    )
    cutoff = func.timezone("UTC", func.now()) - func.make_interval(
        0, 0, 0, 0, 0, 0, threshold_sec
    )
    result = await db.execute(
        select(DeviceFsmSnapshot, Device)
        .join(Device, Device.id == DeviceFsmSnapshot.device_id)
        .outerjoin(TenantSettings, TenantSettings.org_id == Device.org_id)
        .where(DeviceFsmSnapshot.state == DeviceFsmState.RECONNECTING.value)
        .where(DeviceFsmSnapshot.reconnecting_since.is_not(None))
        .where(DeviceFsmSnapshot.reconnecting_since <= cutoff)
        .order_by(DeviceFsmSnapshot.reconnecting_since.asc())
        .limit(limit)
    )
    return _rows_to_reconnecting_candidates(result.all())


async def _list_stale_reconnecting_fallback(
    db: AsyncSession,
    *,
    limit: int,
) -> list[ReconnectingCandidate]:
    """Full scan + Python filter — fine for SQLite tests and small fleets."""
    result = await db.execute(
        select(DeviceFsmSnapshot, Device)
        .join(Device, Device.id == DeviceFsmSnapshot.device_id)
        .where(DeviceFsmSnapshot.state == DeviceFsmState.RECONNECTING.value)
        .where(DeviceFsmSnapshot.reconnecting_since.is_not(None))
        .order_by(DeviceFsmSnapshot.reconnecting_since.asc())
    )
    candidates = _rows_to_reconnecting_candidates(result.all())
    stale = await filter_past_dead_threshold(db, candidates)
    return stale[:limit]


async def filter_past_dead_threshold(
    db: AsyncSession,
    candidates: list[ReconnectingCandidate],
    *,
    thresholds: dict[str, int] | None = None,
    default_threshold_sec: int = DEFAULT_DEAD_THRESHOLD_SEC,
) -> list[ReconnectingCandidate]:
    if not candidates:
        return []
    org_ids = list({c.org_id for c in candidates})
    if thresholds is None:
        from db.crud.tenant_settings import get_dead_thresholds_map

        thresholds = await get_dead_thresholds_map(db, org_ids)
    now = datetime.now(timezone.utc)
    stale: list[ReconnectingCandidate] = []
    for candidate in candidates:
        since = candidate.snapshot.reconnecting_since
        if since is None:
            continue
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        threshold = thresholds.get(candidate.org_id, default_threshold_sec)
        elapsed = (now - since).total_seconds()
        if elapsed >= threshold:
            stale.append(candidate)
    return stale


async def refresh_device_state_gauges(db: AsyncSession) -> None:
    from sqlalchemy import func

    from web.metrics import device_state_count

    result = await db.execute(
        select(DeviceFsmSnapshot.state, func.count())
        .group_by(DeviceFsmSnapshot.state)
    )
    counts = {state: count for state, count in result.all()}
    for state in DeviceFsmState:
        try:
            device_state_count.labels(state=state.value).set(
                counts.get(state.value, 0)
            )
        except Exception:
            pass


async def list_reconnecting_past_ttl(
    db: AsyncSession,
    *,
    ttl_seconds: int | None = None,
    limit: int = 500,
) -> list[DeviceFsmSnapshot]:
    """Devices in RECONNECTING longer than TTL — hook for DF-T-02-005 dead detection."""
    ttl = ttl_seconds if ttl_seconds is not None else RECONNECTING_TTL_SECONDS
    cutoff_dt = datetime.now(timezone.utc) - timedelta(seconds=ttl)
    result = await db.execute(
        select(DeviceFsmSnapshot)
        .where(DeviceFsmSnapshot.state == DeviceFsmState.RECONNECTING.value)
        .where(DeviceFsmSnapshot.reconnecting_since.is_not(None))
        .where(DeviceFsmSnapshot.reconnecting_since <= cutoff_dt)
        .limit(limit)
    )
    return list(result.scalars().all())
