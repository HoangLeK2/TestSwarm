"""Idempotent and privacy-bounded funnel event recording."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import ServiceCampaign
from db.models.ai_device_lab_funnel import AiLabFunnelEvent

FUNNEL_STEPS = (
    "landing_view",
    "start_click",
    "app_submitted",
    "scenario_approved",
    "payment_completed",
    "readiness_started",
)
CLIENT_FUNNEL_STEPS = frozenset(FUNNEL_STEPS[:2])
SERVER_FUNNEL_STEPS = frozenset(FUNNEL_STEPS[2:])
_STEP_ORDER = {name: index for index, name in enumerate(FUNNEL_STEPS)}
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_ATTRIBUTION_KEYS = frozenset(
    {"utm_source", "utm_medium", "utm_campaign", "utm_content", "referrer_host"}
)
_SENSITIVE_KEY = re.compile(
    r"token|secret|password|email|phone|cookie|authorization", re.IGNORECASE
)


class FunnelInvariantError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClientFunnelEvent:
    event_id: str
    event_name: str
    occurred_at: datetime
    attribution: dict[str, str]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise FunnelInvariantError("FUNNEL_TIMEZONE_REQUIRED")
    return value.astimezone(UTC)


def _validate_opaque(value: str, *, code: str) -> str:
    normalized = value.strip()
    if not _OPAQUE_ID.fullmatch(normalized) or "@" in normalized:
        raise FunnelInvariantError(code)
    return normalized


def _sanitize_attribution(value: dict[str, str]) -> dict[str, str]:
    if len(value) > len(_ATTRIBUTION_KEYS):
        raise FunnelInvariantError("FUNNEL_ATTRIBUTION_INVALID")
    sanitized: dict[str, str] = {}
    for key, raw in value.items():
        if key not in _ATTRIBUTION_KEYS or _SENSITIVE_KEY.search(key):
            raise FunnelInvariantError("FUNNEL_ATTRIBUTION_INVALID")
        if not isinstance(raw, str):
            raise FunnelInvariantError("FUNNEL_ATTRIBUTION_INVALID")
        item = raw.strip()
        if (
            not item
            or len(item) > 128
            or "@" in item
            or any(ord(char) < 32 for char in item)
        ):
            raise FunnelInvariantError("FUNNEL_ATTRIBUTION_INVALID")
        if key == "referrer_host" and any(char in item for char in "/?#"):
            raise FunnelInvariantError("FUNNEL_ATTRIBUTION_INVALID")
        sanitized[key] = item
    return sanitized


async def _locked_campaign(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    lock: bool = True,
) -> ServiceCampaign:
    statement = select(ServiceCampaign).where(
        ServiceCampaign.org_id == org_id,
        ServiceCampaign.id == service_campaign_id,
    )
    if lock:
        statement = statement.with_for_update()
    campaign = (await db.execute(statement)).scalar_one_or_none()
    if campaign is None:
        raise FunnelInvariantError("FUNNEL_CAMPAIGN_NOT_FOUND")
    return campaign


async def _record(
    db: AsyncSession,
    *,
    campaign: ServiceCampaign,
    event_id: str,
    event_name: str,
    source_type: str,
    occurred_at: datetime,
    source_ref: str | None = None,
    attribution: dict[str, str] | None = None,
) -> AiLabFunnelEvent:
    existing_step = (
        await db.execute(
            select(AiLabFunnelEvent).where(
                AiLabFunnelEvent.org_id == campaign.org_id,
                AiLabFunnelEvent.service_campaign_id == campaign.id,
                AiLabFunnelEvent.event_name == event_name,
            )
        )
    ).scalar_one_or_none()
    if existing_step is not None:
        return existing_step
    normalized_event_id = _validate_opaque(event_id, code="FUNNEL_EVENT_ID_INVALID")
    reused = (
        await db.execute(
            select(AiLabFunnelEvent).where(
                AiLabFunnelEvent.org_id == campaign.org_id,
                AiLabFunnelEvent.event_id == normalized_event_id,
            )
        )
    ).scalar_one_or_none()
    if reused is not None:
        raise FunnelInvariantError("FUNNEL_EVENT_ID_REUSED")
    row = AiLabFunnelEvent(
        org_id=campaign.org_id,
        service_campaign_id=campaign.id,
        acquisition_id=campaign.creation_intent_key or campaign.id,
        event_id=normalized_event_id,
        event_name=event_name,
        source_type=source_type,
        source_ref=source_ref,
        attribution=attribution or {},
        source_occurred_at=_utc(occurred_at),
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        existing_step = (
            await db.execute(
                select(AiLabFunnelEvent).where(
                    AiLabFunnelEvent.org_id == campaign.org_id,
                    AiLabFunnelEvent.service_campaign_id == campaign.id,
                    AiLabFunnelEvent.event_name == event_name,
                )
            )
        ).scalar_one_or_none()
        if existing_step is not None:
            return existing_step
        raise FunnelInvariantError("FUNNEL_EVENT_ID_REUSED") from exc
    return row


async def record_client_acquisition(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    events: tuple[ClientFunnelEvent, ...],
    now: datetime,
) -> tuple[AiLabFunnelEvent, ...]:
    if not events:
        return ()
    if len(events) != 2 or tuple(event.event_name for event in events) != tuple(
        FUNNEL_STEPS[:2]
    ):
        raise FunnelInvariantError("FUNNEL_CLIENT_SEQUENCE_INVALID")
    observed = [_utc(event.occurred_at) for event in events]
    current = _utc(now)
    if observed != sorted(observed):
        raise FunnelInvariantError("FUNNEL_CLIENT_SEQUENCE_INVALID")
    if observed[0] < current - timedelta(days=30) or observed[-1] > current + timedelta(
        minutes=5
    ):
        raise FunnelInvariantError("FUNNEL_CLIENT_TIME_INVALID")
    validated = tuple(
        (
            _validate_opaque(event.event_id, code="FUNNEL_EVENT_ID_INVALID"),
            _sanitize_attribution(event.attribution),
        )
        for event in events
    )
    if len({event_id for event_id, _ in validated}) != len(validated):
        raise FunnelInvariantError("FUNNEL_EVENT_ID_REUSED")
    campaign = await _locked_campaign(
        db, org_id=org_id, service_campaign_id=service_campaign_id
    )
    rows = []
    for event, (event_id, attribution) in zip(events, validated, strict=True):
        if event.event_name not in CLIENT_FUNNEL_STEPS:
            raise FunnelInvariantError("FUNNEL_CLIENT_SEQUENCE_INVALID")
        rows.append(
            await _record(
                db,
                campaign=campaign,
                event_id=event_id,
                event_name=event.event_name,
                source_type="client",
                occurred_at=event.occurred_at,
                attribution=attribution,
            )
        )
    return tuple(rows)


async def record_server_funnel_event(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    event_name: str,
    source_ref: str,
    occurred_at: datetime,
) -> AiLabFunnelEvent:
    if event_name not in SERVER_FUNNEL_STEPS:
        raise FunnelInvariantError("FUNNEL_SERVER_EVENT_INVALID")
    campaign = await _locked_campaign(
        db, org_id=org_id, service_campaign_id=service_campaign_id, lock=False
    )
    return await _record(
        db,
        campaign=campaign,
        event_id=f"server:{event_name}:{campaign.id}",
        event_name=event_name,
        source_type="server",
        source_ref=_validate_opaque(source_ref, code="FUNNEL_SOURCE_REF_INVALID"),
        occurred_at=occurred_at,
    )


async def list_campaign_funnel(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
) -> tuple[AiLabFunnelEvent, ...]:
    await _locked_campaign(
        db, org_id=org_id, service_campaign_id=service_campaign_id, lock=False
    )
    rows = list(
        (
            await db.execute(
                select(AiLabFunnelEvent).where(
                    AiLabFunnelEvent.org_id == org_id,
                    AiLabFunnelEvent.service_campaign_id == service_campaign_id,
                )
            )
        )
        .scalars()
        .all()
    )
    rows.sort(key=lambda row: (_STEP_ORDER[row.event_name], row.source_occurred_at))
    return tuple(rows)
