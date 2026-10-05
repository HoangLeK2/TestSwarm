"""Append-only Play participation observations and continuity projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import ServiceCampaign
from db.models.ai_device_lab_participation import ParticipationEvent, TrackParticipation


class ParticipationInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecordParticipation:
    org_id: str
    package_name: str
    track_name: str
    pseudonymous_account_ref: str
    masked_label: str
    event_type: str
    source_type: str
    evidence_grade: str
    observed_at: datetime
    recorded_by: str
    service_campaign_id: str | None = None
    source_ref: str | None = None
    evidence_ref: str | None = None
    reviewed_by: str | None = None
    correction_of_id: str | None = None
    limitations: str | None = None


_EVENT_TYPES = frozenset(
    {"invited", "opted_in", "installed", "opened", "lost", "rejoined", "unknown", "corrected"}
)
_APPROVED_GRADES = frozenset({"operator_attested", "provider_verified"})


def _utc_comparable(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _next_projection(
    identity: TrackParticipation,
    command: RecordParticipation,
) -> tuple[str, int, str | None]:
    status = identity.current_status
    segment = identity.active_segment_no
    gap_reason = identity.gap_reason
    if command.event_type == "lost":
        return "lost", segment, "continuity_lost"
    if command.event_type in {"opted_in", "rejoined"}:
        if command.evidence_grade not in _APPROVED_GRADES:
            return "unknown", segment, "reviewed_opt_in_evidence_required"
        if status != "opted_in":
            segment += 1
        return "opted_in", segment, None
    if command.event_type in {"invited", "installed", "opened"} and status != "opted_in":
        return "unknown", segment, f"{command.event_type}_does_not_prove_opt_in"
    if command.event_type == "unknown":
        return "unknown", segment, "participation_unknown"
    return status, segment, gap_reason


async def record_participation(
    db: AsyncSession,
    command: RecordParticipation,
) -> tuple[TrackParticipation, ParticipationEvent]:
    if command.event_type not in _EVENT_TYPES:
        raise ParticipationInvariantError("unsupported participation event")
    if not command.pseudonymous_account_ref.strip():
        raise ParticipationInvariantError("pseudonymous account reference is required")
    if command.reviewed_by is None and command.evidence_grade in _APPROVED_GRADES:
        raise ParticipationInvariantError("reviewer is required for approved evidence")
    if command.service_campaign_id:
        campaign = await db.scalar(
            select(ServiceCampaign.id).where(
                ServiceCampaign.id == command.service_campaign_id,
                ServiceCampaign.org_id == command.org_id,
                ServiceCampaign.package_name == command.package_name,
            )
        )
        if campaign is None:
            raise ParticipationInvariantError("campaign is outside participation scope")

    identity = (
        await db.execute(
            select(TrackParticipation)
            .where(
                TrackParticipation.org_id == command.org_id,
                TrackParticipation.package_name == command.package_name,
                TrackParticipation.track_name == command.track_name,
                TrackParticipation.pseudonymous_account_ref
                == command.pseudonymous_account_ref,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if identity is None:
        identity = TrackParticipation(
            org_id=command.org_id,
            service_campaign_id=command.service_campaign_id,
            package_name=command.package_name,
            track_name=command.track_name,
            pseudonymous_account_ref=command.pseudonymous_account_ref,
            masked_label=command.masked_label,
            current_status="unknown",
            evidence_grade="none",
            active_segment_no=0,
        )
        db.add(identity)
        await db.flush()

    is_latest = (
        identity.last_observed_at is None
        or _utc_comparable(command.observed_at)
        >= _utc_comparable(identity.last_observed_at)
    )
    status, segment, gap_reason = _next_projection(identity, command)
    review_state = "approved" if command.reviewed_by else "pending"
    event = ParticipationEvent(
        org_id=command.org_id,
        participation_id=identity.id,
        event_type=command.event_type,
        source_type=command.source_type,
        source_ref=command.source_ref,
        evidence_ref=command.evidence_ref,
        evidence_grade=command.evidence_grade,
        review_state=review_state,
        observed_at=command.observed_at,
        recorded_by=command.recorded_by,
        reviewed_by=command.reviewed_by,
        reviewed_at=datetime.now(timezone.utc) if command.reviewed_by else None,
        segment_no=segment,
        correction_of_id=command.correction_of_id,
        limitations=command.limitations,
    )
    db.add(event)
    if is_latest and review_state == "approved":
        identity.current_status = status
        identity.evidence_grade = command.evidence_grade
        identity.active_segment_no = segment
        identity.last_observed_at = command.observed_at
        identity.gap_reason = gap_reason
    await db.flush()
    return identity, event
