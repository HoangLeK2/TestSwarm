"""Deterministic full-cohort report manifests used by API and PDF renderer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import RunAttempt, RunSlot, ServiceCampaign
from db.models.ai_device_lab_delivery import EvidenceItem
from db.models.ai_device_lab_participation import TrackParticipation
from db.models.ai_device_lab_quality import AppIssue, RetestRequest
from db.models.ai_device_lab_report import ReportSnapshot
from db.models.ai_device_lab_runtime import QuotaLedgerEntry


@dataclass(frozen=True, slots=True)
class BuildReport:
    org_id: str
    service_campaign_id: str
    idempotency_key: str
    schema_version: str
    builder_version: str
    cutoff_at: datetime
    created_by: str


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def build_report_snapshot(db: AsyncSession, command: BuildReport) -> ReportSnapshot:
    existing = (
        await db.execute(
            select(ReportSnapshot).where(
                ReportSnapshot.org_id == command.org_id,
                ReportSnapshot.service_campaign_id == command.service_campaign_id,
                ReportSnapshot.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.schema_version != command.schema_version
            or existing.builder_version != command.builder_version
            or _utc(existing.cutoff_at) != _utc(command.cutoff_at)
            or existing.created_by != command.created_by
        ):
            raise ValueError("report idempotency key was reused with different input")
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
        raise ValueError("service campaign not found")
    slots = list(
        (
            await db.execute(
                select(RunSlot)
                .where(
                    RunSlot.org_id == command.org_id,
                    RunSlot.service_campaign_id == campaign.id,
                    RunSlot.created_at <= command.cutoff_at,
                )
                .order_by(RunSlot.service_day, RunSlot.lane_id)
            )
        ).scalars()
    )
    attempts = list(
        (
            await db.execute(
                select(RunAttempt)
                .where(
                    RunAttempt.org_id == command.org_id,
                    RunAttempt.service_campaign_id == campaign.id,
                    RunAttempt.created_at <= command.cutoff_at,
                )
                .order_by(RunAttempt.created_at, RunAttempt.id)
            )
        ).scalars()
    )
    evidence = list(
        (
            await db.execute(
                select(EvidenceItem)
                .where(
                    EvidenceItem.org_id == command.org_id,
                    EvidenceItem.service_campaign_id == campaign.id,
                    EvidenceItem.created_at <= command.cutoff_at,
                )
                .order_by(EvidenceItem.created_at, EvidenceItem.id)
            )
        ).scalars()
    )
    participants = list(
        (
            await db.execute(
                select(TrackParticipation).where(
                    TrackParticipation.org_id == command.org_id,
                    TrackParticipation.service_campaign_id == campaign.id,
                )
            )
        ).scalars()
    )
    issues = list(
        (
            await db.execute(
                select(AppIssue).where(
                    AppIssue.org_id == command.org_id,
                    AppIssue.service_campaign_id == campaign.id,
                    AppIssue.created_at <= command.cutoff_at,
                )
            )
        ).scalars()
    )
    retests = list(
        (
            await db.execute(
                select(RetestRequest)
                .join(AppIssue, AppIssue.id == RetestRequest.issue_id)
                .where(
                    RetestRequest.org_id == command.org_id,
                    AppIssue.service_campaign_id == campaign.id,
                    RetestRequest.created_at <= command.cutoff_at,
                )
            )
        ).scalars()
    )
    quota = list(
        (
            await db.execute(
                select(QuotaLedgerEntry).where(
                    QuotaLedgerEntry.org_id == command.org_id,
                    QuotaLedgerEntry.service_campaign_id == campaign.id,
                    QuotaLedgerEntry.occurred_at <= command.cutoff_at,
                )
            )
        ).scalars()
    )
    terminal = {"succeeded", "failed", "blocked", "timeout", "missed", "cancelled"}
    manifest = {
        "schema_version": command.schema_version,
        "builder_version": command.builder_version,
        "org_id": command.org_id,
        "service_campaign_id": campaign.id,
        "cutoff_at": command.cutoff_at.isoformat(),
        "source_ids": {
            "slots": [row.id for row in slots],
            "attempts": [row.id for row in attempts],
            "evidence": [row.id for row in evidence],
            "issues": [row.id for row in issues],
            "retests": [row.id for row in retests],
            "quota": [row.id for row in quota],
        },
        "service": {
            "planned_slots": len(slots),
            "attempts": len(attempts),
            "terminal_slots": sum(row.execution_status in terminal for row in slots),
            "missed_slots": sum(row.execution_status == "missed" for row in slots),
        },
        "app_quality": {
            "evaluated": sum(row.app_verdict in {"pass", "fail", "inconclusive"} for row in slots),
            "pass": sum(row.app_verdict == "pass" for row in slots),
            "fail": sum(row.app_verdict == "fail" for row in slots),
            "inconclusive": sum(row.app_verdict == "inconclusive" for row in slots),
            "open_issues": sum(row.status == "open" for row in issues),
            "fixed_retests": sum(row.verdict == "fixed" for row in retests),
        },
        "play_participation": {
            "identities": len(participants),
            "opted_in": sum(row.current_status == "opted_in" for row in participants),
            "unknown_or_lost": sum(row.current_status != "opted_in" for row in participants),
        },
        "evidence": {
            "available": sum(row.status == "available" for row in evidence),
            "missing": sum(row.status == "missing" for row in evidence),
            "unsupported": sum(row.status == "unsupported" for row in evidence),
            "expired_or_deleted": sum(row.status in {"expired", "deleted"} for row in evidence),
        },
        "quota": {
            "reserved": sum(row.quantity for row in quota if row.entry_type == "reserved"),
            "consumed": sum(row.quantity for row in quota if row.entry_type == "consumed"),
            "released": sum(row.quantity for row in quota if row.entry_type == "released"),
            "adjusted": sum(row.quantity for row in quota if row.entry_type == "adjusted"),
        },
    }
    version = int(
        await db.scalar(
            select(func.max(ReportSnapshot.version)).where(
                ReportSnapshot.org_id == command.org_id,
                ReportSnapshot.service_campaign_id == campaign.id,
            )
        )
        or 0
    ) + 1
    snapshot = ReportSnapshot(
        org_id=command.org_id,
        service_campaign_id=campaign.id,
        version=version,
        idempotency_key=command.idempotency_key,
        schema_version=command.schema_version,
        cutoff_at=command.cutoff_at,
        builder_version=command.builder_version,
        manifest=manifest,
        manifest_sha256=_digest(manifest),
        status="ready",
        created_by=command.created_by,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def attach_pdf_output(
    db: AsyncSession,
    *,
    org_id: str,
    report_id: str,
    manifest_sha256: str,
    object_key: str,
    pdf_sha256: str,
) -> ReportSnapshot:
    report = (
        await db.execute(
            select(ReportSnapshot)
            .where(ReportSnapshot.id == report_id, ReportSnapshot.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None or report.manifest_sha256 != manifest_sha256:
        raise ValueError("PDF output does not match the report manifest")
    if report.pdf_object_key and (
        report.pdf_object_key != object_key or report.pdf_sha256 != pdf_sha256
    ):
        raise ValueError("published report output is immutable")
    report.pdf_object_key = object_key
    report.pdf_sha256 = pdf_sha256
    report.status = "published"
    await db.flush()
    return report
