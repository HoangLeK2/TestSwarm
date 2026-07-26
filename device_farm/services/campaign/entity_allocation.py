"""Org-scoped source-pool resolution and deterministic device allocation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.external_entity import ExecutionEntityAssignment, ExternalEntity
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
            assignment.device_id: assignment.entity
            for assignment in self.assignments
        }


@dataclass(frozen=True, slots=True)
class SourcePoolSpec:
    platform: str
    entity_type: str
    search: str | None = None
    statuses: tuple[str, ...] = DEFAULT_POOL_STATUSES


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
        filters.append(
            ExternalEntity.display_name.ilike(f"%{spec.search.strip()}%")
        )
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
        filters.append(
            ExternalEntity.display_name.ilike(f"%{spec.search.strip()}%")
        )
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
