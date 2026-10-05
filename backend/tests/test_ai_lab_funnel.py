from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from api.deps import _get_current_user
from db.models.ai_device_lab_funnel import AiLabFunnelEvent
from db.models.device import Device
from services.ai_device_lab.billing import (
    AcceptPaymentEvent,
    CreateOrder,
    PriceSnapshot,
    accept_payment_event,
    create_order,
)
from services.ai_device_lab.fleet import (
    ReserveCohort,
    record_hygiene_result,
    reserve_cohort,
)
from services.ai_device_lab.funnel import (
    FunnelInvariantError,
    list_campaign_funnel,
    record_server_funnel_event,
)
from services.ai_device_lab.operations import (
    AssessOperationalReadiness,
    SignOperationalTarget,
    assess_operational_readiness,
    sign_operational_target,
)
from services.ai_device_lab.readiness import (
    ReadinessPolicy,
    StartCampaign,
    start_campaign,
)
from tenancy.context import set_current_org_id, tenant_context
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    build_tenancy_api_app,
    seed_two_org_fixture,
)
from tests.test_ai_lab_billing_checkout import _seed_approved_campaign


def _owner(user_id: str, org_id: str):
    async def override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@example.invalid",
            name=user_id,
            role="owner",
            org_role="owner",
            is_active=True,
            org_id=org_id,
        )

    return override


@pytest.mark.asyncio
async def test_acquisition_events_are_ordered_deduplicated_private_and_tenant_scoped(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)
    app.dependency_overrides[_get_current_user] = _owner(USER_A, ORG_A)
    now = datetime.now(UTC).replace(microsecond=0)
    payload = {
        "creation_intent_key": "journey-opaque-0001",
        "runtime_campaign_id": seeded["campaign_a"],
        "package_name": "com.example.funnel",
        "timezone": "UTC",
        "plan_version": "adl-14d-v1",
        "acquisition_events": [
            {
                "event_id": "event-landing-0001",
                "event_name": "landing_view",
                "occurred_at": (now - timedelta(seconds=2)).isoformat(),
                "attribution": {
                    "utm_source": "docs",
                    "referrer_host": "example.test",
                },
            },
            {
                "event_id": "event-start-0001",
                "event_name": "start_click",
                "occurred_at": (now - timedelta(seconds=1)).isoformat(),
                "attribution": {"utm_source": "docs"},
            },
        ],
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/api/ai-device-lab/service-campaigns", json=payload)
        replay = await client.post("/api/ai-device-lab/service-campaigns", json=payload)
        assert first.status_code == 201, first.text
        assert replay.status_code == 201, replay.text
        campaign_id = first.json()["id"]
        funnel = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/funnel"
        )
        assert funnel.status_code == 200, funnel.text
        body = funnel.json()
        assert body["acquisition_id"] == "journey-opaque-0001"
        assert body["completed_steps"] == 2
        assert body["next_step"] == "app_submitted"
        assert [event["event_name"] for event in body["events"]] == [
            "landing_view",
            "start_click",
        ]
        serialized = funnel.text.lower()
        assert "email" not in serialized
        assert "token" not in serialized

        invalid = dict(payload)
        invalid["acquisition_events"] = [
            payload["acquisition_events"][0],
            {
                **payload["acquisition_events"][1],
                "attribution": {"utm_source": "person@example.test"},
            },
        ]
        rejected = await client.post(
            "/api/ai-device-lab/service-campaigns", json=invalid
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "FUNNEL_ATTRIBUTION_INVALID"

        app.dependency_overrides[_get_current_user] = _owner(USER_B, ORG_B)
        outside = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/funnel"
        )
        assert outside.status_code == 404

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            count = await db.scalar(select(func.count()).select_from(AiLabFunnelEvent))
            assert count == 2


@pytest.mark.asyncio
async def test_server_transitions_emit_one_authoritative_event_per_funnel_step(
    tenancy_session_factory,
) -> None:
    campaign_id, _ = await _seed_approved_campaign(tenancy_session_factory)
    paid_at = datetime(2026, 10, 6, tzinfo=UTC)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign_id,
                    idempotency_key="funnel-order-0001",
                    created_by=USER_A,
                    price=PriceSnapshot(
                        plan_version="adl-14d-v1",
                        pricing_version="price-v1",
                        policy_version="refund-v1",
                        amount_minor=100_000,
                        currency="VND",
                        quota={"slots": 168},
                    ),
                ),
            )
            command = AcceptPaymentEvent(
                org_id=ORG_A,
                order_id=order.id,
                provider="sandbox",
                provider_event_id="provider-funnel-paid-0001",
                event_type="payment.settled",
                source_occurred_at=paid_at,
                signature_verified=True,
                amount_minor=100_000,
                currency="VND",
            )
            await accept_payment_event(db, command)
            await accept_payment_event(db, command)
            readiness = await record_server_funnel_event(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign_id,
                event_name="readiness_started",
                source_ref="readiness-intent-0001",
                occurred_at=paid_at + timedelta(minutes=1),
            )
            assert (
                await record_server_funnel_event(
                    db,
                    org_id=ORG_A,
                    service_campaign_id=campaign_id,
                    event_name="readiness_started",
                    source_ref="readiness-intent-0001",
                    occurred_at=paid_at + timedelta(minutes=1),
                )
            ).id == readiness.id
            rows = await list_campaign_funnel(
                db, org_id=ORG_A, service_campaign_id=campaign_id
            )
            await db.commit()

    assert [row.event_name for row in rows] == [
        "app_submitted",
        "scenario_approved",
        "payment_completed",
        "readiness_started",
    ]
    assert all(row.source_type == "server" for row in rows)
    assert all("provider" not in (row.source_ref or "") for row in rows)

    with tenant_context(ORG_B):
        async with tenancy_session_factory() as db:
            with pytest.raises(FunnelInvariantError, match="FUNNEL_CAMPAIGN_NOT_FOUND"):
                await list_campaign_funnel(
                    db, org_id=ORG_B, service_campaign_id=campaign_id
                )


@pytest.mark.asyncio
async def test_ready_campaign_start_emits_final_funnel_step_once(
    tenancy_session_factory,
) -> None:
    campaign_id, _ = await _seed_approved_campaign(tenancy_session_factory)
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign_id,
                    idempotency_key="funnel-ready-order-0001",
                    created_by=USER_A,
                    price=PriceSnapshot(
                        plan_version="adl-14d-v1",
                        pricing_version="price-v1",
                        policy_version="refund-v1",
                        amount_minor=100_000,
                        currency="VND",
                        quota={"slots": 168},
                    ),
                ),
            )
            await accept_payment_event(
                db,
                AcceptPaymentEvent(
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    provider_event_id="provider-funnel-ready-0001",
                    event_type="payment.settled",
                    source_occurred_at=now,
                    signature_verified=True,
                    amount_minor=100_000,
                    currency="VND",
                ),
            )
            devices = [
                Device(
                    id=f"adl-funnel-device-{ordinal:02d}",
                    org_id=ORG_A,
                    user_id=USER_A,
                    serial=f"ADL-FUNNEL-{ordinal:02d}",
                    name=f"ADL funnel {ordinal:02d}",
                    last_seen=now,
                )
                for ordinal in range(1, 13)
            ]
            db.add_all(devices)
            await db.flush()
            for device in devices:
                await record_hygiene_result(
                    db,
                    device_id=device.id,
                    actor_id=USER_A,
                    protocol_version="hygiene-v1",
                    reset_succeeded=True,
                    readback_clean=True,
                    evidence_ref=f"evidence/{device.id}",
                    active_run=False,
                    service_campaign_id=campaign_id,
                )
            await reserve_cohort(
                db,
                ReserveCohort(
                    org_id=ORG_A,
                    service_campaign_id=campaign_id,
                    device_ids=tuple(device.id for device in devices),
                    starts_at=now - timedelta(minutes=1),
                    ends_at=now + timedelta(days=14),
                    created_by=USER_A,
                ),
            )
            target = await sign_operational_target(
                db,
                SignOperationalTarget(
                    org_id=ORG_A,
                    version="funnel-ready-ops-v1",
                    capacity={
                        "concurrent_campaigns": 1,
                        "devices": 12,
                        "jobs_per_minute": 12,
                        "artifact_bytes": 1_000_000,
                    },
                    slo={"api_p95_ms": 500, "dispatch_lag_p95_seconds": 30},
                    recovery={"rpo_seconds": 300, "rto_seconds": 1800},
                    alerting={
                        "owner": "fixture-oncall",
                        "escalation_ref": "runbook://fixture",
                    },
                    signed_by=USER_A,
                    signed_at=now,
                ),
            )
            await assess_operational_readiness(
                db,
                AssessOperationalReadiness(
                    org_id=ORG_A,
                    target_id=target.id,
                    dependency_states={
                        "encryption": True,
                        "payment_provider": True,
                        "object_storage": True,
                        "worker": True,
                        "relay": True,
                    },
                    build_ref="fixture-build",
                    schema_version="162",
                    observed_at=now,
                ),
            )
            command = StartCampaign(
                org_id=ORG_A,
                service_campaign_id=campaign_id,
                idempotency_key="funnel-ready-start-0001",
                now=now,
                policy=ReadinessPolicy(
                    version="readiness-v1",
                    require_participation=False,
                ),
            )
            first = await start_campaign(db, command)
            replay = await start_campaign(db, command)
            rows = await list_campaign_funnel(
                db, org_id=ORG_A, service_campaign_id=campaign_id
            )
            await db.commit()

    assert first.started is True
    assert replay.started is True
    assert first.intent is not None
    assert replay.intent is not None
    assert replay.intent.id == first.intent.id
    assert [row.event_name for row in rows] == [
        "app_submitted",
        "scenario_approved",
        "payment_completed",
        "readiness_started",
    ]
    assert sum(row.event_name == "readiness_started" for row in rows) == 1
    assert rows[-1].source_ref == first.intent.id
