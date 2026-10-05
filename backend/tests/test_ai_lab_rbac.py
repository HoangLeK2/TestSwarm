from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from api.deps import _get_current_user
from tenancy.context import set_current_org_id
from tests.tenancy_test_support import (
    ORG_A,
    USER_A,
    build_tenancy_api_app,
    seed_two_org_fixture,
)


def _identity(*, role: str, org_role: str | None):
    async def _override():
        set_current_org_id(ORG_A)
        return SimpleNamespace(
            id=USER_A,
            email="adl-rbac@example.invalid",
            name="ADL RBAC",
            role=role,
            org_role=org_role,
            is_active=True,
            org_id=ORG_A,
        )

    return _override


@pytest.mark.asyncio
async def test_operator_can_read_but_cannot_create_manage_or_execute_ai_lab_actions(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)
    transport = ASGITransport(app=app)

    app.dependency_overrides[_get_current_user] = _identity(
        role="owner",
        org_role="owner",
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/ai-device-lab/service-campaigns",
            json={
                "creation_intent_key": "adl-rbac-campaign",
                "runtime_campaign_id": seeded["campaign_a"],
                "package_name": "com.example.adl.rbac",
                "timezone": "UTC",
                "plan_version": "adl-14d-v1",
            },
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]

    app.dependency_overrides[_get_current_user] = _identity(
        role="operator",
        org_role=None,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        readable = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}"
        )
        reconciliation_readable = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}"
            "/payment-reconciliations"
        )
        create_denied = await client.post(
            "/api/ai-device-lab/service-campaigns",
            json={
                "creation_intent_key": "adl-rbac-denied",
                "runtime_campaign_id": seeded["campaign_a"],
                "package_name": "com.example.adl.denied",
                "timezone": "UTC",
                "plan_version": "adl-14d-v1",
            },
        )
        manage_denied = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}"
            "/reports/report-does-not-matter/publish"
        )
        execute_denied = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/start",
            json={"idempotency_key": "adl-rbac-denied-start"},
        )
        checkout_denied = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}"
            "/wizard/payment/checkout",
            json={
                "approval_id": "approval-does-not-matter",
                "idempotency_key": "adl-rbac-denied-checkout",
            },
        )

    assert readable.status_code == 200, readable.text
    assert reconciliation_readable.status_code == 200, reconciliation_readable.text
    assert create_denied.status_code == 403, create_denied.text
    assert manage_denied.status_code == 403, manage_denied.text
    assert execute_denied.status_code == 403, execute_denied.text
    assert checkout_denied.status_code == 403, checkout_denied.text
