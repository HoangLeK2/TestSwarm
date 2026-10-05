from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from api.deps import _get_current_user
from db.models.ai_device_lab_billing import (
    PaymentIntent,
    PaymentReconciliationJob,
    ServiceEntitlement,
    ServiceOrder,
)
from services.ai_device_lab.billing_checkout import (
    CheckoutProviderSession,
    StartWizardCheckout,
    configure_checkout_provider_adapter,
    start_wizard_checkout,
)
from services.ai_device_lab.billing_reconciliation import (
    PaymentProviderSnapshot,
    run_payment_reconciliation_batch,
)
from services.ai_device_lab.intake import (
    ApproveScenario,
    CompleteGeneration,
    approve_scenario,
    complete_generation,
    scenario_version_content_hash,
    start_generation,
)
from services.ai_device_lab.service_campaigns import (
    CreateServiceCampaign,
    create_service_campaign,
)
from services.ai_device_lab.wizard import (
    SaveWizardDraft,
    WizardDraftInput,
    save_wizard_draft,
)
from services.operation_policy import OperationPolicy
from tenancy.context import set_current_org_id, tenant_context
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    build_tenancy_api_app,
    seed_two_org_fixture,
)


class CheckoutAdapter:
    def __init__(
        self,
        session: CheckoutProviderSession | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.session = session
        self.error = error
        self.calls: list[dict] = []

    async def create_or_lookup_checkout(self, **kwargs) -> CheckoutProviderSession:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.session is not None
        return self.session


class LookupReconciliationAdapter:
    def __init__(self, snapshot: PaymentProviderSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str | None, str]] = []

    async def fetch_payment(
        self,
        *,
        provider_reference: str | None,
        idempotency_key: str,
    ) -> PaymentProviderSnapshot:
        self.calls.append((provider_reference, idempotency_key))
        return self.snapshot


def _policy() -> OperationPolicy:
    return OperationPolicy(
        version="adl-operations-v1",
        app_package="com.example.checkout",
        allowed_actions=frozenset({"navigation.open"}),
        allowed_targets=frozenset({"com.example.checkout"}),
    )


async def _seed_approved_campaign(session_factory) -> tuple[str, str]:
    seeded = await seed_two_org_fixture(session_factory)
    with tenant_context(ORG_A):
        async with session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.checkout",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                ),
            )
            intake = await save_wizard_draft(
                db,
                SaveWizardDraft(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    service_campaign_id=campaign.id,
                    expected_revision=0,
                    draft=WizardDraftInput(
                        package_name="com.example.checkout",
                        closed_track_link=(
                            "https://play.google.com/store/apps/details?"
                            "id=com.example.checkout"
                        ),
                        test_goal="Open the app and verify Home",
                        test_environment={"locale": "en-US"},
                        version_name="1.0.0",
                        version_code="100",
                        source_kind="closed_track",
                        source_ref="play-closed-track",
                        checksum_sha256=None,
                    ),
                ),
            )
            operation = await start_generation(
                db,
                intake_id=intake.id,
                org_id=ORG_A,
                operation_id="checkout-generation-1",
            )
            version = await complete_generation(
                db,
                CompleteGeneration(
                    org_id=ORG_A,
                    operation_id=operation.operation_id,
                    scenario_name="Checkout safe scenario",
                    scenario={
                        "steps": [
                            {
                                "type": "launch_app",
                                "package": "com.example.checkout",
                                "semantic_action": "navigation.open",
                                "policy_target": "com.example.checkout",
                            },
                            {
                                "type": "assert_element",
                                "by": "text",
                                "value": "Home",
                                "timeout": 5,
                            },
                        ]
                    },
                    policy=_policy(),
                ),
            )
            approval = await approve_scenario(
                db,
                ApproveScenario(
                    org_id=ORG_A,
                    operation_id=operation.operation_id,
                    scenario_version_id=version.id,
                    expected_content_hash=scenario_version_content_hash(version),
                    approved_by=USER_A,
                    policy=_policy(),
                ),
            )
            await db.commit()
            return campaign.id, approval.id


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_DEVICE_LAB_PAYMENT_PROVIDER", "sandbox")
    monkeypatch.setenv("AI_DEVICE_LAB_PRICE_MINOR", "129900")
    monkeypatch.setenv("AI_DEVICE_LAB_CURRENCY", "USD")
    monkeypatch.setenv("AI_DEVICE_LAB_PRICING_VERSION", "pricing-v1")
    monkeypatch.setenv("AI_DEVICE_LAB_BILLING_POLICY_VERSION", "refund-v1")
    monkeypatch.setenv(
        "AI_DEVICE_LAB_CHECKOUT_ALLOWED_HOSTS",
        "checkout.sandbox.example",
    )
    monkeypatch.setenv(
        "AI_DEVICE_LAB_CHECKOUT_RETURN_URL",
        "https://app.example/ai-device-lab/payment-return",
    )
    monkeypatch.setenv(
        "AI_DEVICE_LAB_CHECKOUT_CANCEL_URL",
        "https://app.example/ai-device-lab/payment-cancel",
    )


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
async def test_checkout_reuses_one_order_intent_and_provider_idempotency_key(
    tenancy_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    campaign_id, approval_id = await _seed_approved_campaign(
        tenancy_session_factory
    )
    now = datetime(2026, 10, 4, tzinfo=UTC)
    adapter = CheckoutAdapter(
        CheckoutProviderSession(
            provider_reference="provider-checkout-1",
            checkout_url="https://checkout.sandbox.example/session/opaque-1",
            expires_at=now + timedelta(minutes=30),
        )
    )
    configure_checkout_provider_adapter("sandbox", adapter)
    try:
        with tenant_context(ORG_A):
            async with tenancy_session_factory() as db:
                first = await start_wizard_checkout(
                    db,
                    StartWizardCheckout(
                        org_id=ORG_A,
                        service_campaign_id=campaign_id,
                        approval_id=approval_id,
                        idempotency_key="checkout-browser-tab-a",
                        actor_id=USER_A,
                        now=now,
                    ),
                )
                replay = await start_wizard_checkout(
                    db,
                    StartWizardCheckout(
                        org_id=ORG_A,
                        service_campaign_id=campaign_id,
                        approval_id=approval_id,
                        idempotency_key="checkout-browser-tab-b",
                        actor_id=USER_A,
                        now=now + timedelta(seconds=1),
                    ),
                )
                order_count = await db.scalar(
                    select(func.count()).select_from(ServiceOrder)
                )
                intent_count = await db.scalar(
                    select(func.count()).select_from(PaymentIntent)
                )
    finally:
        configure_checkout_provider_adapter("sandbox", None)

    assert first.order_id == replay.order_id
    assert first.intent_id == replay.intent_id
    assert first.status == replay.status == "awaiting_payment"
    assert first.checkout_url == replay.checkout_url
    assert order_count == 1
    assert intent_count == 1
    assert len(adapter.calls) == 2
    assert adapter.calls[0]["idempotency_key"] == "checkout-browser-tab-a"
    assert adapter.calls[1]["idempotency_key"] == "checkout-browser-tab-a"
    assert adapter.calls[0]["amount_minor"] == 129900
    assert adapter.calls[0]["currency"] == "USD"
    assert "campaign_id=" in adapter.calls[0]["return_url"]


@pytest.mark.asyncio
async def test_checkout_api_is_tenant_scoped_and_never_returns_provider_reference(
    tenancy_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    campaign_id, approval_id = await _seed_approved_campaign(
        tenancy_session_factory
    )
    now = datetime.now(UTC)
    adapter = CheckoutAdapter(
        CheckoutProviderSession(
            provider_reference="private-provider-reference",
            checkout_url="https://checkout.sandbox.example/session/customer-safe",
            expires_at=now + timedelta(minutes=30),
        )
    )
    configure_checkout_provider_adapter("sandbox", adapter)
    app = build_tenancy_api_app(tenancy_session_factory)
    transport = ASGITransport(app=app)
    try:
        app.dependency_overrides[_get_current_user] = _owner(USER_A, ORG_A)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            checkout = await client.post(
                f"/api/ai-device-lab/service-campaigns/{campaign_id}"
                "/wizard/payment/checkout",
                json={
                    "approval_id": approval_id,
                    "idempotency_key": "checkout-api-owner",
                },
            )
            wizard = await client.get(
                f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard"
            )
        app.dependency_overrides[_get_current_user] = _owner(USER_B, ORG_B)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            hidden = await client.post(
                f"/api/ai-device-lab/service-campaigns/{campaign_id}"
                "/wizard/payment/checkout",
                json={
                    "approval_id": approval_id,
                    "idempotency_key": "checkout-api-cross-tenant",
                },
            )
    finally:
        configure_checkout_provider_adapter("sandbox", None)

    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["status"] == "awaiting_payment"
    assert checkout.json()["checkout_url"].startswith(
        "https://checkout.sandbox.example/"
    )
    assert "provider_reference" not in checkout.text
    assert "private-provider-reference" not in checkout.text
    assert wizard.status_code == 200, wizard.text
    assert wizard.json()["payment"]["checkout_status"] == "awaiting_payment"
    assert "private-provider-reference" not in wizard.text
    assert hidden.status_code == 404, hidden.text


@pytest.mark.asyncio
async def test_checkout_timeout_reconciles_by_original_provider_lookup_key(
    tenancy_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    campaign_id, approval_id = await _seed_approved_campaign(
        tenancy_session_factory
    )
    now = datetime(2026, 10, 4, tzinfo=UTC)
    checkout_adapter = CheckoutAdapter(error=TimeoutError("private timeout body"))
    configure_checkout_provider_adapter("sandbox", checkout_adapter)
    try:
        with tenant_context(ORG_A):
            async with tenancy_session_factory() as db:
                result = await start_wizard_checkout(
                    db,
                    StartWizardCheckout(
                        org_id=ORG_A,
                        service_campaign_id=campaign_id,
                        approval_id=approval_id,
                        idempotency_key="checkout-timeout-key",
                        actor_id=USER_A,
                        now=now,
                    ),
                )
                intent = await db.get(PaymentIntent, result.intent_id)
                job = await db.scalar(select(PaymentReconciliationJob))
    finally:
        configure_checkout_provider_adapter("sandbox", None)

    assert result.status == "uncertain"
    assert result.checkout_url is None
    assert intent is not None and intent.last_error_code == "CHECKOUT_PROVIDER_TIMEOUT"
    assert "private timeout body" not in repr(intent.__dict__)
    assert job is not None
    assert job.provider_reference is None
    assert job.provider_lookup_key == "checkout-timeout-key"

    reconciliation = LookupReconciliationAdapter(
        PaymentProviderSnapshot(
            state="paid",
            version="provider-lookup-v1",
            observed_at=now + timedelta(seconds=2),
            amount_minor=129900,
            currency="USD",
        )
    )
    reconciled = await run_payment_reconciliation_batch(
        tenancy_session_factory,
        adapters={"sandbox": reconciliation},
        now=now + timedelta(seconds=2),
    )
    assert reconciled.resolved == 1
    assert reconciliation.calls == [(None, "checkout-timeout-key")]
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            order = await db.get(ServiceOrder, result.order_id)
            stored_intent = await db.get(PaymentIntent, result.intent_id)
            entitlement = await db.scalar(select(ServiceEntitlement))
    assert order is not None and order.status == "paid"
    assert stored_intent is not None and stored_intent.status == "paid"
    assert entitlement is not None and entitlement.state == "active"
