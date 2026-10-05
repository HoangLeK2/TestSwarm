"""Append-only idempotent quota accounting with non-negative balance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import ServiceCampaign
from db.models.ai_device_lab_runtime import QuotaLedgerEntry


class QuotaInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AppendQuotaEntry:
    org_id: str
    service_campaign_id: str
    charge_key: str
    entry_type: str
    resource_type: str
    quantity: int
    occurred_at: datetime
    run_attempt_id: str | None = None
    metadata: dict | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def append_quota_entry(
    db: AsyncSession,
    command: AppendQuotaEntry,
) -> QuotaLedgerEntry:
    if command.quantity <= 0:
        raise QuotaInvariantError("quota quantity must be positive")
    if command.entry_type not in {"reserved", "consumed", "released", "adjusted"}:
        raise QuotaInvariantError("unsupported quota entry type")
    existing = (
        await db.execute(
            select(QuotaLedgerEntry).where(
                QuotaLedgerEntry.org_id == command.org_id,
                QuotaLedgerEntry.charge_key == command.charge_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.service_campaign_id != command.service_campaign_id
            or existing.run_attempt_id != command.run_attempt_id
            or existing.entry_type != command.entry_type
            or existing.resource_type != command.resource_type
            or existing.quantity != command.quantity
            or existing.metadata_json != (command.metadata or {})
            or _utc(existing.occurred_at) != _utc(command.occurred_at)
        ):
            raise QuotaInvariantError("quota charge key was reused with different input")
        return existing
    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(
                ServiceCampaign.id == command.service_campaign_id,
                ServiceCampaign.org_id == command.org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise QuotaInvariantError("service campaign not found")
    signed_quantity = case(
        (QuotaLedgerEntry.entry_type.in_(("reserved", "adjusted")), QuotaLedgerEntry.quantity),
        else_=-QuotaLedgerEntry.quantity,
    )
    balance = int(
        await db.scalar(
            select(func.coalesce(func.sum(signed_quantity), 0)).where(
                QuotaLedgerEntry.org_id == command.org_id,
                QuotaLedgerEntry.service_campaign_id == command.service_campaign_id,
                QuotaLedgerEntry.resource_type == command.resource_type,
            )
        )
        or 0
    )
    delta = command.quantity if command.entry_type in {"reserved", "adjusted"} else -command.quantity
    if balance + delta < 0:
        raise QuotaInvariantError("quota balance cannot become negative")
    entry = QuotaLedgerEntry(
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
        run_attempt_id=command.run_attempt_id,
        charge_key=command.charge_key,
        entry_type=command.entry_type,
        resource_type=command.resource_type,
        quantity=command.quantity,
        metadata_json=command.metadata or {},
        occurred_at=command.occurred_at,
    )
    db.add(entry)
    await db.flush()
    return entry
