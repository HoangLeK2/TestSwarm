"""Org-scoped source-pool resolution and deterministic device allocation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.device import Device
from db.models.external_entity import (
    DeviceTargetGroup,
    ExecutionEntityAssignment,
    ExternalEntity,
)
from tenancy.context import use_tenant_scope

UNAVAILABLE_STATUSES = frozenset({"archived", "unavailable", "deleted"})
DEFAULT_POOL_STATUSES = ("candidate", "active", "available")


class EntityAllocationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class EntityAssignment:
    device_id: str
    entity: Any


@dataclass(frozen=True, slots=True)
class EntityAllocationPlan:
    assignments: list[EntityAssignment]
    available_count: int

    @property
    def entity_by_device(self) -> dict[str, ExternalEntity]:
        return {
            assignment.device_id: assignment.entity for assignment in self.assignments
        }


@dataclass(frozen=True, slots=True)
class SourcePoolSpec:
    platform: str
    entity_type: str
    search: str | None = None
    statuses: tuple[str, ...] = DEFAULT_POOL_STATUSES
    output_prefix: str | None = None


@dataclass(frozen=True, slots=True)
class SourcePoolPage:
    entities: list[ExternalEntity]
    next_cursor: str | None
    exhausted: bool


@dataclass(frozen=True, slots=True)
class AssignedTargetItem:
    device_serial: str
    entity: ExternalEntity


@dataclass(frozen=True, slots=True)
class AssignedTargetPage:
    items: list[AssignedTargetItem]
    next_cursor: str | None
    exhausted: bool


def _assigned_target_filters(
    *,
    org_id: str,
    spec: SourcePoolSpec,
    snapshot_at: datetime,
) -> list[Any]:
    filters: list[Any] = [
        DeviceTargetGroup.org_id == org_id,
        DeviceTargetGroup.assigned_at <= snapshot_at,
        ExternalEntity.org_id == org_id,
        ExternalEntity.platform == spec.platform.strip().lower(),
        ExternalEntity.entity_type == spec.entity_type.strip().lower(),
        ExternalEntity.status.in_(spec.statuses),
    ]
    if spec.search:
        filters.append(ExternalEntity.display_name.ilike(f"%{spec.search.strip()}%"))
    return filters


def _decode_assigned_cursor(cursor: str) -> tuple[int, str, str]:
    try:
        value = json.loads(cursor)
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError
        return int(value[0]), str(value[1]), str(value[2])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid assigned target cursor") from exc


def _encode_assigned_cursor(position: int, device_id: str, row_id: str) -> str:
    return json.dumps([position, device_id, row_id], separators=(",", ":"))


async def load_assigned_target_page(
    db: AsyncSession,
    *,
    org_id: str,
    spec: SourcePoolSpec,
    dispatch_id: str,
    device_serials: Sequence[str],
    snapshot_at: datetime,
    cursor: str | None,
    limit: int,
) -> AssignedTargetPage:
    """Load assigned targets in fair position order without crossing devices."""
    if limit < 1 or limit > 2_000:
        raise ValueError("assigned target page limit must be between 1 and 2000")
    if not device_serials:
        return AssignedTargetPage([], None, True)

    processed = exists(
        select(ExecutionEntityAssignment.id).where(
            ExecutionEntityAssignment.org_id == org_id,
            ExecutionEntityAssignment.dispatch_id == dispatch_id,
            ExecutionEntityAssignment.device_id == DeviceTargetGroup.device_id,
            ExecutionEntityAssignment.external_entity_id
            == DeviceTargetGroup.external_entity_id,
        )
    )
    filters = [
        *_assigned_target_filters(
            org_id=org_id,
            spec=spec,
            snapshot_at=snapshot_at,
        ),
        Device.serial.in_(device_serials),
        ~processed,
    ]
    if cursor:
        position, device_id, row_id = _decode_assigned_cursor(cursor)
        filters.append(
            tuple_(
                DeviceTargetGroup.position,
                DeviceTargetGroup.device_id,
                DeviceTargetGroup.id,
            )
            > tuple_(position, device_id, row_id)
        )

    statement = (
        select(DeviceTargetGroup, Device.serial, ExternalEntity)
        .join(
            Device,
            (Device.id == DeviceTargetGroup.device_id)
            & (Device.org_id == DeviceTargetGroup.org_id),
        )
        .join(
            ExternalEntity,
            (ExternalEntity.id == DeviceTargetGroup.external_entity_id)
            & (ExternalEntity.org_id == DeviceTargetGroup.org_id),
        )
        .where(*filters)
        .order_by(
            DeviceTargetGroup.position,
            DeviceTargetGroup.device_id,
            DeviceTargetGroup.id,
        )
        .limit(limit + 1)
    )
    with use_tenant_scope(org_id):
        rows = list((await db.execute(statement)).all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        assignment = page_rows[-1][0]
        next_cursor = _encode_assigned_cursor(
            assignment.position,
            assignment.device_id,
            assignment.id,
        )
    return AssignedTargetPage(
        items=[
            AssignedTargetItem(device_serial=str(row[1]), entity=row[2])
            for row in page_rows
        ],
        next_cursor=next_cursor,
        exhausted=not has_more,
    )


async def count_assigned_targets_by_device(
    db: AsyncSession,
    *,
    org_id: str,
    spec: SourcePoolSpec,
    device_ids: Sequence[str],
    snapshot_at: datetime,
) -> dict[str, int]:
    if not device_ids:
        return {}
    statement = (
        select(DeviceTargetGroup.device_id, func.count(DeviceTargetGroup.id))
        .join(
            ExternalEntity,
            (ExternalEntity.id == DeviceTargetGroup.external_entity_id)
            & (ExternalEntity.org_id == DeviceTargetGroup.org_id),
        )
        .where(
            *_assigned_target_filters(
                org_id=org_id,
                spec=spec,
                snapshot_at=snapshot_at,
            ),
            DeviceTargetGroup.device_id.in_(device_ids),
        )
        .group_by(DeviceTargetGroup.device_id)
    )
    with use_tenant_scope(org_id):
        rows = list((await db.execute(statement)).all())
    return {str(device_id): int(count) for device_id, count in rows}


async def load_source_pool_page(
    db: AsyncSession,
    *,
    org_id: str,
    spec: SourcePoolSpec,
    dispatch_id: str,
    snapshot_at: datetime,
    cursor: str | None,
    limit: int,
) -> SourcePoolPage:
    """Read a stable, bounded frontier page without using the database as a queue."""
    if limit < 1 or limit > 2_000:
        raise ValueError("Source pool page limit must be between 1 and 2000")
    processed_in_dispatch = exists(
        select(ExecutionEntityAssignment.id).where(
            ExecutionEntityAssignment.org_id == org_id,
            ExecutionEntityAssignment.dispatch_id == dispatch_id,
            ExecutionEntityAssignment.external_entity_id == ExternalEntity.id,
        )
    )
    active_in_other_dispatch = exists(
        select(ExecutionEntityAssignment.id).where(
            ExecutionEntityAssignment.org_id == org_id,
            ExecutionEntityAssignment.external_entity_id == ExternalEntity.id,
            ExecutionEntityAssignment.dispatch_id != dispatch_id,
            ExecutionEntityAssignment.status == "assigned",
            ExecutionEntityAssignment.completed_at.is_(None),
        )
    )
    filters = [
        ExternalEntity.org_id == org_id,
        ExternalEntity.platform == spec.platform.strip().lower(),
        ExternalEntity.entity_type == spec.entity_type.strip().lower(),
        ExternalEntity.status.in_(spec.statuses),
        ExternalEntity.created_at <= snapshot_at,
        ~processed_in_dispatch,
        ~active_in_other_dispatch,
    ]
    if cursor:
        filters.append(ExternalEntity.id > cursor)
    if spec.search:
        filters.append(ExternalEntity.display_name.ilike(f"%{spec.search.strip()}%"))
    with use_tenant_scope(org_id):
        rows = list(
            (
                await db.scalars(
                    select(ExternalEntity)
                    .where(*filters)
                    .order_by(ExternalEntity.id)
                    .limit(limit + 1)
                )
            ).all()
        )
    has_more = len(rows) > limit
    page = rows[:limit]
    return SourcePoolPage(
        entities=page,
        next_cursor=str(page[-1].id) if has_more and page else None,
        exhausted=not has_more,
    )


def plan_one_per_device(
    *,
    device_ids: Sequence[str],
    entities: Sequence[Any],
    available_count: int | None = None,
) -> EntityAllocationPlan:
    unavailable_ids = [
        str(entity.id)
        for entity in entities
        if str(getattr(entity, "status", "")).lower() in UNAVAILABLE_STATUSES
    ]
    if unavailable_ids:
        raise EntityAllocationError(
            "One or more external entities are unavailable",
            code="EXTERNAL_ENTITY_UNAVAILABLE",
            details={"entity_ids": unavailable_ids},
        )

    total_available = len(entities) if available_count is None else available_count
    if len(entities) < len(device_ids):
        raise EntityAllocationError(
            "Source pool has "
            f"{total_available} available sources for {len(device_ids)} devices",
            code="ENTITY_POOL_EXHAUSTED",
            details={
                "device_count": len(device_ids),
                "available_entity_count": total_available,
                "missing_count": len(device_ids) - len(entities),
            },
        )

    return EntityAllocationPlan(
        assignments=[
            EntityAssignment(device_id=device_id, entity=entity)
            for device_id, entity in zip(device_ids, entities, strict=False)
        ],
        available_count=total_available,
    )


async def load_source_pool(
    db: AsyncSession,
    *,
    org_id: str,
    spec: SourcePoolSpec,
    limit: int,
    lock_sources: bool = False,
) -> tuple[list[ExternalEntity], int]:
    active_assignment = exists(
        select(ExecutionEntityAssignment.id).where(
            ExecutionEntityAssignment.org_id == org_id,
            ExecutionEntityAssignment.external_entity_id == ExternalEntity.id,
            ExecutionEntityAssignment.status == "assigned",
            ExecutionEntityAssignment.completed_at.is_(None),
        )
    )
    filters = [
        ExternalEntity.org_id == org_id,
        ExternalEntity.platform == spec.platform.strip().lower(),
        ExternalEntity.entity_type == spec.entity_type.strip().lower(),
        ExternalEntity.status.in_(spec.statuses),
        ~active_assignment,
    ]
    if spec.search:
        filters.append(ExternalEntity.display_name.ilike(f"%{spec.search.strip()}%"))
    with use_tenant_scope(org_id):
        if lock_sources:
            statement = (
                select(ExternalEntity)
                .where(*filters)
                .order_by(ExternalEntity.last_seen_at.desc(), ExternalEntity.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = list((await db.scalars(statement)).all())
            return rows, len(rows)

        result = await db.execute(
            select(
                ExternalEntity,
                func.count().over().label("available_count"),
            )
            .where(*filters)
            .order_by(ExternalEntity.last_seen_at.desc(), ExternalEntity.id)
            .limit(limit)
        )
        result_rows = result.all()
        return (
            [row[0] for row in result_rows],
            int(result_rows[0][1]) if result_rows else 0,
        )


async def load_source_pool_snapshot(
    db: AsyncSession,
    *,
    org_id: str,
    spec: SourcePoolSpec,
    entity_ids: Sequence[str],
    lock_sources: bool,
) -> list[ExternalEntity]:
    if not entity_ids:
        return []
    active_assignment = exists(
        select(ExecutionEntityAssignment.id).where(
            ExecutionEntityAssignment.org_id == org_id,
            ExecutionEntityAssignment.external_entity_id == ExternalEntity.id,
            ExecutionEntityAssignment.status == "assigned",
            ExecutionEntityAssignment.completed_at.is_(None),
        )
    )
    filters = [
        ExternalEntity.org_id == org_id,
        ExternalEntity.id.in_(entity_ids),
        ExternalEntity.platform == spec.platform.strip().lower(),
        ExternalEntity.entity_type == spec.entity_type.strip().lower(),
        ExternalEntity.status.in_(spec.statuses),
        ~active_assignment,
    ]
    if spec.search:
        filters.append(ExternalEntity.display_name.ilike(f"%{spec.search.strip()}%"))
    statement = select(ExternalEntity).where(*filters)
    if lock_sources:
        statement = statement.with_for_update(skip_locked=True)
    with use_tenant_scope(org_id):
        rows = list((await db.scalars(statement)).all())
    by_id = {entity.id: entity for entity in rows}
    return [by_id[entity_id] for entity_id in entity_ids if entity_id in by_id]


async def plan_from_source_pool(
    db: AsyncSession,
    *,
    org_id: str,
    device_ids: Sequence[str],
    spec: SourcePoolSpec,
    policy: str,
    lock_sources: bool = False,
) -> EntityAllocationPlan:
    if policy != "one_per_device":
        raise EntityAllocationError(
            f"Unsupported allocation policy: {policy}",
            code="UNSUPPORTED_ALLOCATION_POLICY",
            details={"allocation_policy": policy},
        )
    entities, total = await load_source_pool(
        db,
        org_id=org_id,
        spec=spec,
        limit=len(device_ids),
        lock_sources=lock_sources,
    )
    return plan_one_per_device(
        device_ids=device_ids,
        entities=entities,
        available_count=total,
    )
