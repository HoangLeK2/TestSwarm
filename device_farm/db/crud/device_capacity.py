"""Capacity planning aggregate queries (DF-T-02-010)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device_group import get_group
from db.crud.fleet_stats import FleetStatsNotFoundError, FleetStatsValidationError, _relay_serials_for_host
from db.models.device import Device
from db.models.device_fsm import DeviceFsmSnapshot
from db.models.device_group import DeviceGroup, DeviceGroupMember
from db.models.enums import DeviceFsmState


AVAILABLE_STATES = {
    DeviceFsmState.UNKNOWN.value,
    DeviceFsmState.CONNECTING.value,
    DeviceFsmState.ONLINE.value,
    DeviceFsmState.RECONNECTING.value,
}


@dataclass
class CapacityFilters:
    organization_id: str
    group_id: Optional[str] = None
    tag: Optional[str] = None
    state: Optional[str] = None
    relay_host: Optional[str] = None


@dataclass
class DeviceIdSample:
    db_id: str
    device_serial: str
    adb_serial: Optional[str]
    relay_serial: Optional[str]


@dataclass
class GroupCapacityRow:
    group_id: str
    total: int
    available: int
    busy: int
    dead: int


@dataclass
class RelayCapacityRow:
    relay_host: str
    total: int
    available: int
    busy: int
    dead: int


@dataclass
class CapacityReport:
    filters: CapacityFilters
    by_state: dict[str, int] = field(default_factory=dict)
    by_group: list[GroupCapacityRow] = field(default_factory=list)
    by_relay: list[RelayCapacityRow] = field(default_factory=list)
    sample_devices: list[DeviceIdSample] = field(default_factory=list)
    devices_scanned: int = 0
    latency_ms: float = 0.0

    @property
    def summary(self) -> dict[str, int]:
        total = sum(self.by_state.values())
        busy = self.by_state.get(DeviceFsmState.BUSY.value, 0)
        dead = self.by_state.get(DeviceFsmState.DEAD.value, 0)
        available = sum(self.by_state.get(state, 0) for state in AVAILABLE_STATES)
        return {
            "total": total,
            "available": available,
            "busy": busy,
            "dead": dead,
            "reconnecting": self.by_state.get(DeviceFsmState.RECONNECTING.value, 0),
            "connecting": self.by_state.get(DeviceFsmState.CONNECTING.value, 0),
            "unknown": self.by_state.get(DeviceFsmState.UNKNOWN.value, 0),
        }


def _device_scope(filters: CapacityFilters, relay_serials: set[str] | None) -> list:
    clauses = [Device.org_id == filters.organization_id]
    if filters.group_id:
        clauses.append(
            Device.id.in_(
                select(DeviceGroupMember.device_id).where(
                    DeviceGroupMember.group_id == filters.group_id
                )
            )
        )
    if filters.tag:
        tag = filters.tag.strip()
        clauses.append(or_(Device.tags.ilike(f"%{tag}%"), Device.tags.ilike(f"{tag},%")))
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
    if filters.state:
        state = filters.state.strip().lower()
        try:
            DeviceFsmState(state)
        except ValueError as exc:
            raise FleetStatsValidationError(f"invalid state {filters.state!r}") from exc
        clauses.append(func.coalesce(DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value) == state)
    return clauses


async def query_capacity_report(
    db: AsyncSession,
    *,
    filters: CapacityFilters,
    sample_limit: int = 20,
) -> CapacityReport:
    started = time.perf_counter()
    if filters.relay_host is not None and not filters.relay_host.strip():
        raise FleetStatsValidationError("relay_host must not be empty")

    relay_serials: set[str] | None = None
    if filters.relay_host:
        relay_serials = await _relay_serials_for_host(db, filters.organization_id, filters.relay_host)

    if filters.group_id:
        group = await get_group(db, filters.group_id)
        if group is None or group.org_id != filters.organization_id:
            raise FleetStatsNotFoundError(f"device group {filters.group_id!r} not found")

    scope = _device_scope(filters, relay_serials)
    report = CapacityReport(filters=filters)

    state_expr = func.coalesce(DeviceFsmSnapshot.state, DeviceFsmState.UNKNOWN.value).label("state")
    state_rows = await db.execute(
        select(state_expr, func.count().label("cnt"))
        .select_from(Device)
        .outerjoin(DeviceFsmSnapshot, DeviceFsmSnapshot.device_id == Device.id)
        .where(*scope)
        .group_by(state_expr)
    )
    by_state = {state.value: 0 for state in DeviceFsmState}
    for row in state_rows.all():
        key = str(row.state or DeviceFsmState.UNKNOWN.value).lower()
        if key in by_state:
            by_state[key] = int(row.cnt or 0)
        else:
            by_state[DeviceFsmState.UNKNOWN.value] += int(row.cnt or 0)
    report.by_state = by_state
    report.devices_scanned = sum(by_state.values())

    if filters.group_id is None:
        group_rows = await db.execute(
            select(
                DeviceGroupMember.group_id,
                state_expr,
                func.count().label("cnt"),
            )
            .select_from(Device)
            .join(DeviceGroupMember, DeviceGroupMember.device_id == Device.id)
            .outerjoin(DeviceFsmSnapshot, DeviceFsmSnapshot.device_id == Device.id)
            .where(Device.org_id == filters.organization_id)
            .group_by(DeviceGroupMember.group_id, state_expr)
        )
        grouped: dict[str, dict[str, int]] = {}
        for group_id, state, cnt in group_rows.all():
            bucket = grouped.setdefault(str(group_id), {})
            bucket[str(state)] = int(cnt or 0)
        for group_id, counts in grouped.items():
            total = sum(counts.values())
            busy = counts.get(DeviceFsmState.BUSY.value, 0)
            dead = counts.get(DeviceFsmState.DEAD.value, 0)
            available = sum(counts.get(state, 0) for state in AVAILABLE_STATES)
            report.by_group.append(
                GroupCapacityRow(
                    group_id=group_id,
                    total=total,
                    available=available,
                    busy=busy,
                    dead=dead,
                )
            )

    if filters.relay_host:
        report.by_relay.append(
            RelayCapacityRow(
                relay_host=filters.relay_host.strip(),
                total=report.summary["total"],
                available=report.summary["available"],
                busy=report.summary["busy"],
                dead=report.summary["dead"],
            )
        )

    sample_rows = await db.execute(
        select(Device.id, Device.device_serial, Device.adb_serial, Device.relay_serial, Device.serial)
        .outerjoin(DeviceFsmSnapshot, DeviceFsmSnapshot.device_id == Device.id)
        .where(*scope)
        .order_by(Device.created_at.asc())
        .limit(sample_limit)
    )
    for db_id, device_serial, adb_serial, relay_serial, serial in sample_rows.all():
        report.sample_devices.append(
            DeviceIdSample(
                db_id=str(db_id),
                device_serial=str(device_serial or serial),
                adb_serial=adb_serial,
                relay_serial=relay_serial,
            )
        )

    report.latency_ms = (time.perf_counter() - started) * 1000
    return report
