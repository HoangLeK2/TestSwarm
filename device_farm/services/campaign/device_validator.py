"""Device validation before campaign dispatch (DF-T-04-008)."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device import get_devices_by_ids
from db.crud.device_group import get_groups_by_ids, snapshot_groups_device_ids
from db.crud.device_state import get_device_states_map
from db.models.enums import DeviceFsmState


@dataclass(slots=True)
class ResolvedTargetEntry:
    device_id: str
    source_kind: str
    source_ref_id: str


@dataclass(slots=True)
class DeviceValidationResult:
    entries: list[ResolvedTargetEntry] = field(default_factory=list)
    not_found_ids: list[str] = field(default_factory=list)
    cross_org_ids: list[str] = field(default_factory=list)
    offline_ids: list[str] = field(default_factory=list)
    devices_by_id: dict = field(default_factory=dict)


class DispatchValidationError(Exception):
    def __init__(self, message: str, *, code: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


async def resolve_dispatch_targets(
    db: AsyncSession,
    *,
    org_id: str,
    device_ids: list[str] | None,
    device_group_ids: list[str] | None,
) -> list[ResolvedTargetEntry]:
    """Expand explicit device ids and device groups into a deduplicated target list."""
    entries: list[ResolvedTargetEntry] = []
    seen: set[str] = set()

    for raw_id in device_ids or []:
        device_id = (raw_id or "").strip()
        if not device_id or device_id in seen:
            continue
        seen.add(device_id)
        entries.append(
            ResolvedTargetEntry(
                device_id=device_id,
                source_kind="explicit",
                source_ref_id=device_id,
            )
        )

    group_ids = [(g or "").strip() for g in (device_group_ids or [])]
    group_ids = [g for g in group_ids if g]
    if group_ids:
        groups = await get_groups_by_ids(db, group_ids)
        missing = [gid for gid in group_ids if gid not in groups]
        if missing:
            raise DispatchValidationError(
                f"Device group not found: {missing[0]}",
                code="DEVICE_GROUP_NOT_FOUND",
                details={"device_group_ids": missing},
            )
        cross_org = [gid for gid, grp in groups.items() if grp.org_id != org_id]
        if cross_org:
            raise DispatchValidationError(
                f"Device group not found: {cross_org[0]}",
                code="DEVICE_GROUP_NOT_FOUND",
                details={"device_group_ids": cross_org},
            )

        membership = await snapshot_groups_device_ids(
            db, group_ids, for_update=True
        )
        for group_id in group_ids:
            for device_id in membership.get(group_id, []):
                if device_id in seen:
                    continue
                seen.add(device_id)
                entries.append(
                    ResolvedTargetEntry(
                        device_id=device_id,
                        source_kind="device_group",
                        source_ref_id=group_id,
                    )
                )

    return entries


_DISPATCHABLE_STATES = frozenset({DeviceFsmState.ONLINE, DeviceFsmState.BUSY})


def _is_dispatchable_state(state: str | None) -> bool:
    if not state:
        return False
    try:
        return DeviceFsmState(state) in _DISPATCHABLE_STATES
    except ValueError:
        return False


async def validate_devices_for_dispatch(
    db: AsyncSession,
    *,
    org_id: str,
    entries: list[ResolvedTargetEntry],
    require_online: bool = True,
    allow_partial: bool = False,
) -> DeviceValidationResult:
    """Validate targets with batched device + FSM lookups (2 queries, not 2N)."""
    result = DeviceValidationResult(entries=[])
    if not entries:
        return result

    device_ids = [e.device_id for e in entries]
    devices_by_id = await get_devices_by_ids(db, device_ids)
    states_by_id = await get_device_states_map(db, device_ids) if require_online else {}

    for entry in entries:
        device = devices_by_id.get(entry.device_id)
        if device is None:
            result.not_found_ids.append(entry.device_id)
            continue
        if device.org_id != org_id:
            result.cross_org_ids.append(entry.device_id)
            continue
        if require_online:
            state_row = states_by_id.get(entry.device_id)
            if not _is_dispatchable_state(
                state_row.state if state_row else None
            ):
                result.offline_ids.append(entry.device_id)
                if allow_partial:
                    continue
        result.entries.append(entry)

    result.devices_by_id = devices_by_id
    return result
