"""Aggregate queries for fleet health summary (DF-T-02-013)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device_group import get_group
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.device_group import DeviceGroupMember
from db.models.enums import DeviceFsmState, McpSessionStatus, SessionOwnerType
from db.models.mcp_session import McpSession
from db.models.relay_agent import RelayAgent
from services.fleet_stats import (
    FleetStatsFilters,
    FleetStatsResult,
    SessionOwnerAnomaly,
    derive_session_owner_type,
    empty_owner_counts,
    empty_state_counts,
)


class FleetStatsValidationError(ValueError):
    """Invalid filter input for fleet stats."""


class FleetStatsNotFoundError(LookupError):
    """Referenced filter resource is missing or out of organization scope."""


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
        raise FleetStatsNotFoundError(f"relay host {host!r} not found in organization")
    serials: set[str] = set()
    for relay in relays:
        for serial in relay.serials or []:
            cleaned = str(serial or "").strip()
            if cleaned:
                serials.add(cleaned)
    return serials


def _device_scope_filters(
    org_id: str,
    *,
    group_id: str | None,
    relay_serials: set[str] | None,
):
    clauses = [Device.org_id == org_id]
    if group_id:
        clauses.append(
            Device.id.in_(
                select(DeviceGroupMember.device_id).where(
                    DeviceGroupMember.group_id == group_id
                )
            )
        )
    if relay_serials is not None:
        if not relay_serials:
            clauses.append(false())
        else:
            clauses.append(
                or_(Device.serial.in_(relay_serials), Device.adb_serial.in_(relay_serials))
            )
    return clauses


async def query_fleet_stats(
    db: AsyncSession,
    *,
    org_id: str,
    group_id: str | None = None,
    relay_host: str | None = None,
    include_owner_anomalies: bool = False,
) -> FleetStatsResult:
    if relay_host is not None and not relay_host.strip():
        raise FleetStatsValidationError("relay_host must not be empty")

    relay_serials: set[str] | None = None
    if relay_host:
        relay_serials = await _relay_serials_for_host(db, org_id, relay_host)

    if group_id:
        group = await get_group(db, group_id)
        if group is None or group.org_id != org_id:
            raise FleetStatsNotFoundError(f"device group {group_id!r} not found")

    scope = _device_scope_filters(org_id, group_id=group_id, relay_serials=relay_serials)
    filters = FleetStatsFilters(
        organization_id=org_id,
        group_id=group_id,
        relay_host=relay_host.strip() if relay_host else None,
    )
    result = FleetStatsResult(filters=filters)

    state_expr = func.coalesce(
        DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value
    ).label("state")
    state_rows = await db.execute(
        select(state_expr, func.count().label("cnt"))
        .select_from(Device)
        .outerjoin(DeviceFsmSnapshot, DeviceFsmSnapshot.device_id == Device.id)
        .where(*scope)
        .group_by(state_expr)
    )
    devices_by_state = empty_state_counts()
    for row in state_rows.all():
        state_key = str(row.state or DeviceFsmState.UNKNOWN.value).lower()
        if state_key in devices_by_state:
            devices_by_state[state_key] = int(row.cnt or 0)
        else:
            devices_by_state[DeviceFsmState.UNKNOWN.value] += int(row.cnt or 0)
    result.devices_by_state = devices_by_state

    session_rows = await db.execute(
        select(
            McpSession.id,
            McpSession.device_serial,
            McpSession.user_id,
            Device.id,
            Device.user_id,
        )
        .join(Device, Device.serial == McpSession.device_serial)
        .where(
            *scope,
            McpSession.status == McpSessionStatus.ACTIVE.value,
        )
    )

    owner_counts = empty_owner_counts()
    active_session_ids: set[str] = set()
    for sid, device_serial, session_user_id, device_id, device_user_id in session_rows.all():
        active_session_ids.add(str(sid))
        owner_type = derive_session_owner_type(session_id=str(sid), user_id=session_user_id)
        owner_counts[owner_type.value] += 1

        if not include_owner_anomalies:
            continue

        if session_user_id is None and owner_type == SessionOwnerType.UNKNOWN:
            result.owner_anomalies.append(
                SessionOwnerAnomaly(
                    session_id=str(sid),
                    device_id=str(device_id),
                    device_serial=str(device_serial),
                    owner_type=owner_type.value,
                    owner_id=None,
                    reason="active_session_missing_owner",
                )
            )
        elif session_user_id and device_user_id and str(session_user_id) != str(device_user_id):
            result.owner_anomalies.append(
                SessionOwnerAnomaly(
                    session_id=str(sid),
                    device_id=str(device_id),
                    device_serial=str(device_serial),
                    owner_type=owner_type.value,
                    owner_id=str(session_user_id),
                    reason="session_owner_differs_from_device_owner",
                )
            )

    busy_rows = await db.execute(
        select(
            DeviceFsmSnapshot.session_id,
            Device.id,
            Device.serial,
        )
        .join(Device, Device.id == DeviceFsmSnapshot.device_id)
        .where(
            *scope,
            DeviceFsmSnapshot.state == DeviceFsmState.BUSY.value,
            DeviceFsmSnapshot.session_id.is_not(None),
        )
    )
    for claim_session_id, device_id, device_serial in busy_rows.all():
        claim_id = str(claim_session_id or "").strip()
        if not claim_id or claim_id in active_session_ids:
            continue
        owner_type = derive_session_owner_type(session_id=claim_id, user_id=None)
        owner_counts[owner_type.value] += 1
        if include_owner_anomalies and owner_type == SessionOwnerType.UNKNOWN:
            result.owner_anomalies.append(
                SessionOwnerAnomaly(
                    session_id=claim_id,
                    device_id=str(device_id),
                    device_serial=str(device_serial),
                    owner_type=owner_type.value,
                    owner_id=None,
                    reason="busy_device_without_active_mcp_session",
                )
            )

    result.active_sessions_by_owner = owner_counts
    return result
