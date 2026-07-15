"""Paginated fleet device queries (DF-T-02-007 / DF-T-02-014)."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device_group import get_group
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.device_group import DeviceGroupMember
from db.models.device_reserve_session import DeviceReserveSession
from db.models.enums import DeviceFsmState, SessionOwnerType
from db.models.relay_agent import RelayAgent
from services.fleet_stats import derive_session_owner_type


class FleetQueryValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_QUERY") -> None:
        super().__init__(message)
        self.code = code


class FleetQueryNotFoundError(LookupError):
    pass


ALLOWED_SORTS = {
    "name": (Device.name.asc(), Device.id.asc()),
    "-name": (Device.name.desc(), Device.id.desc()),
    "state": (DeviceFsmSnapshot.state.asc(), Device.id.asc()),
    "-state": (DeviceFsmSnapshot.state.desc(), Device.id.desc()),
    "last_seen_at": (Device.last_seen.asc().nullsfirst(), Device.id.asc()),
    "-last_seen_at": (Device.last_seen.desc().nullslast(), Device.id.desc()),
    "paired_at": (func.coalesce(Device.paired_at, Device.created_at).asc(), Device.id.asc()),
    "-paired_at": (func.coalesce(Device.paired_at, Device.created_at).desc(), Device.id.desc()),
}

DEFAULT_SORT = "-paired_at"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class FleetQueryFilters:
    org_id: str
    state: str | None = None
    group_id: str | None = None
    owner_type: str | None = None
    relay_host: str | None = None
    tag: str | None = None
    q: str | None = None
    device_id: str | None = None
    device_serial: str | None = None
    adb_serial: str | None = None
    relay_serial: str | None = None


@dataclass(frozen=True, slots=True)
class FleetDeviceRow:
    db_id: str
    device_serial: str
    adb_serial: str | None
    relay_serial: str | None
    adb_ip: str | None
    adb_port: int
    name: str
    state: str
    group_ids: list[str]
    current_session_id: str | None
    owner_type: str | None
    owner_id: str | None
    last_seen_at: datetime | None
    model: str
    android_version: str
    paired_at: datetime | None
    sort_key: str | None = None


@dataclass(frozen=True, slots=True)
class FleetQueryPage:
    items: list[FleetDeviceRow]
    next_cursor: str | None
    total: int


def _encode_cursor(org_id: str, sort: str, row: FleetDeviceRow) -> str:
    payload = {
        "org_id": org_id,
        "sort": sort,
        "id": row.db_id,
        "paired_at": (
            row.paired_at.isoformat()
            if row.paired_at
            else (row.last_seen_at.isoformat() if row.last_seen_at else row.db_id)
        ),
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "name": row.name,
        "state": row.state,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str, *, org_id: str, sort: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise FleetQueryValidationError("malformed cursor", code="INVALID_CURSOR") from exc
    if payload.get("org_id") != org_id:
        raise FleetQueryValidationError("cursor organization mismatch", code="INVALID_CURSOR")
    if payload.get("sort") != sort:
        raise FleetQueryValidationError("cursor sort mismatch", code="INVALID_CURSOR")
    return payload


async def _relay_serials_for_host(
    db: AsyncSession,
    org_id: str,
    relay_host: str,
) -> set[str]:
    host = relay_host.strip()
    result = await db.execute(
        select(RelayAgent).where(
            RelayAgent.org_id == org_id,
            or_(RelayAgent.hostname == host, RelayAgent.relay_id == host),
        )
    )
    relays = list(result.scalars().all())
    if not relays:
        raise FleetQueryNotFoundError(f"relay host {host!r} not found in organization")
    serials: set[str] = set()
    for relay in relays:
        for serial in relay.serials or []:
            cleaned = str(serial or "").strip()
            if cleaned:
                serials.add(cleaned)
    return serials


def _build_scope(filters: FleetQueryFilters, relay_serials: set[str] | None) -> list:
    clauses = [Device.org_id == filters.org_id]
    if filters.group_id:
        clauses.append(
            Device.id.in_(
                select(DeviceGroupMember.device_id).where(
                    DeviceGroupMember.group_id == filters.group_id
                )
            )
        )
    if relay_serials is not None:
        if not relay_serials:
            clauses.append(false())
        else:
            clauses.append(
                or_(
                    Device.serial.in_(relay_serials),
                    Device.adb_serial.in_(relay_serials),
                    Device.relay_serial.in_(relay_serials),
                )
            )
    if filters.device_id:
        clauses.append(Device.id == filters.device_id.strip())
    if filters.device_serial:
        clauses.append(Device.device_serial.ilike(f"%{filters.device_serial.strip()}%"))
    if filters.adb_serial:
        clauses.append(Device.adb_serial.ilike(f"%{filters.adb_serial.strip()}%"))
    if filters.relay_serial:
        clauses.append(Device.relay_serial.ilike(f"%{filters.relay_serial.strip()}%"))
    if filters.tag:
        tag = filters.tag.strip()
        clauses.append(or_(Device.tags.ilike(f"%{tag}%"), Device.tags.ilike(f"{tag},%")))
    if filters.q:
        needle = f"%{filters.q.strip()}%"
        clauses.append(
            or_(
                Device.name.ilike(needle),
                Device.device_serial.ilike(needle),
                Device.serial.ilike(needle),
                Device.adb_serial.ilike(needle),
                Device.relay_serial.ilike(needle),
            )
        )
    if filters.state:
        state = filters.state.strip().lower()
        try:
            DeviceFsmState(state)
        except ValueError as exc:
            raise FleetQueryValidationError(f"invalid state {filters.state!r}") from exc
        clauses.append(func.coalesce(DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value) == state)
    return clauses


def _cursor_clause(sort: str, cursor_payload: dict[str, Any]):
    device_id = cursor_payload["id"]
    if sort in {"-paired_at", "paired_at"}:
        value = cursor_payload.get("paired_at")
        if sort == "-paired_at":
            if value is None:
                return or_(Device.paired_at.is_(None), and_(Device.paired_at.is_(None), Device.id < device_id))
            dt = datetime.fromisoformat(value)
            return or_(
                Device.paired_at < dt,
                and_(Device.paired_at == dt, Device.id < device_id),
                and_(Device.paired_at.is_(None)),
            )
        if value is None:
            return or_(Device.paired_at.is_not(None), and_(Device.paired_at.is_(None), Device.id > device_id))
        dt = datetime.fromisoformat(value)
        return or_(Device.paired_at > dt, and_(Device.paired_at == dt, Device.id > device_id))
    if sort in {"-last_seen_at", "last_seen_at"}:
        value = cursor_payload.get("last_seen_at")
        if sort == "-last_seen_at":
            if value is None:
                return or_(Device.last_seen.is_(None), and_(Device.last_seen.is_(None), Device.id < device_id))
            dt = datetime.fromisoformat(value)
            return or_(
                Device.last_seen < dt,
                and_(Device.last_seen == dt, Device.id < device_id),
                Device.last_seen.is_(None),
            )
        if value is None:
            return or_(Device.last_seen.is_not(None), and_(Device.last_seen.is_(None), Device.id > device_id))
        dt = datetime.fromisoformat(value)
        return or_(Device.last_seen > dt, and_(Device.last_seen == dt, Device.id > device_id))
    if sort in {"name", "-name"}:
        name = cursor_payload.get("name") or ""
        if sort == "name":
            return or_(Device.name > name, and_(Device.name == name, Device.id > device_id))
        return or_(Device.name < name, and_(Device.name == name, Device.id < device_id))
    if sort in {"state", "-state"}:
        state = cursor_payload.get("state") or DeviceFsmState.UNKNOWN.value
        if sort == "state":
            return or_(
                func.coalesce(DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value) > state,
                and_(
                    func.coalesce(DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value) == state,
                    Device.id > device_id,
                ),
            )
        return or_(
            func.coalesce(DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value) < state,
            and_(
                func.coalesce(DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value) == state,
                Device.id < device_id,
            ),
        )
    return Device.id < device_id


async def _group_ids_map(db: AsyncSession, device_ids: list[str]) -> dict[str, list[str]]:
    if not device_ids:
        return {}
    result = await db.execute(
        select(DeviceGroupMember.device_id, DeviceGroupMember.group_id).where(
            DeviceGroupMember.device_id.in_(device_ids)
        )
    )
    mapping: dict[str, list[str]] = {did: [] for did in device_ids}
    for device_id, group_id in result.all():
        mapping.setdefault(str(device_id), []).append(str(group_id))
    return mapping


async def _active_sessions_map(
    db: AsyncSession,
    device_ids: list[str],
) -> dict[str, DeviceReserveSession]:
    if not device_ids:
        return {}
    result = await db.execute(
        select(DeviceReserveSession).where(
            DeviceReserveSession.device_id.in_(device_ids),
            DeviceReserveSession.released_at.is_(None),
        )
    )
    return {str(row.device_id): row for row in result.scalars().all()}


def _owner_type_filter_clause(owner_type: str):
    value = owner_type.strip().lower()
    try:
        SessionOwnerType(value)
    except ValueError as exc:
        raise FleetQueryValidationError(f"invalid owner_type {owner_type!r}") from exc
    active = select(DeviceReserveSession.device_id).where(
        DeviceReserveSession.released_at.is_(None),
    )
    if value == SessionOwnerType.USER.value:
        return Device.id.in_(active.where(DeviceReserveSession.owner_type == "manual"))
    return Device.id.in_(active.where(DeviceReserveSession.owner_type == value))


async def query_fleet_devices(
    db: AsyncSession,
    *,
    filters: FleetQueryFilters,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    sort: str = DEFAULT_SORT,
) -> FleetQueryPage:
    if limit < 1 or limit > MAX_LIMIT:
        raise FleetQueryValidationError(
            f"limit must be between 1 and {MAX_LIMIT}",
            code="LIMIT_TOO_LARGE",
        )
    if sort not in ALLOWED_SORTS:
        raise FleetQueryValidationError(f"unsupported sort {sort!r}", code="INVALID_SORT")

    if filters.group_id:
        group = await get_group(db, filters.group_id)
        if group is None or group.org_id != filters.org_id:
            raise FleetQueryNotFoundError(f"device group {filters.group_id!r} not found")

    relay_serials: set[str] | None = None
    if filters.relay_host:
        relay_serials = await _relay_serials_for_host(db, filters.org_id, filters.relay_host)

    scope = _build_scope(filters, relay_serials)
    if filters.owner_type:
        scope.append(_owner_type_filter_clause(filters.owner_type))

    count_q = (
        select(func.count())
        .select_from(Device)
        .outerjoin(DeviceFsmSnapshot, DeviceFsmSnapshot.device_id == Device.id)
        .where(*scope)
    )
    total = int((await db.execute(count_q)).scalar_one() or 0)

    order_by = ALLOWED_SORTS[sort]
    q = (
        select(Device, DeviceFsmSnapshot)
        .outerjoin(DeviceFsmSnapshot, DeviceFsmSnapshot.device_id == Device.id)
        .where(*scope)
        .order_by(*order_by)
        .limit(limit + 1)
    )
    if cursor:
        payload = _decode_cursor(cursor, org_id=filters.org_id, sort=sort)
        q = q.where(_cursor_clause(sort, payload))

    rows = (await db.execute(q)).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    device_ids = [str(device.id) for device, _ in page_rows]
    groups = await _group_ids_map(db, device_ids)
    sessions = await _active_sessions_map(db, device_ids)

    items: list[FleetDeviceRow] = []
    for device, snap in page_rows:
        session = sessions.get(str(device.id))
        owner_type = session.owner_type if session else None
        owner_id = session.owner_id if session else None
        if session and owner_type == "manual":
            owner_type = SessionOwnerType.USER.value
        state = snap.state if snap else DeviceFsmState.UNKNOWN.value
        row = FleetDeviceRow(
            db_id=str(device.id),
            device_serial=str(device.device_serial or device.serial),
            adb_serial=device.adb_serial,
            relay_serial=device.relay_serial,
            adb_ip=device.adb_ip,
            adb_port=int(device.adb_port or 5555),
            name=device.name or "",
            state=state,
            group_ids=groups.get(str(device.id), []),
            current_session_id=session.id if session else (snap.session_id if snap else None),
            owner_type=owner_type,
            owner_id=owner_id,
            last_seen_at=device.last_seen,
            model=device.model or "",
            android_version=device.android_version or "",
            paired_at=device.paired_at,
        )
        items.append(row)

    next_cursor = _encode_cursor(filters.org_id, sort, items[-1]) if has_more and items else None
    return FleetQueryPage(items=items, next_cursor=next_cursor, total=total)
