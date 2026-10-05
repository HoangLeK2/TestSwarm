from __future__ import annotations

import pytest

from db.models.ai_device_lab import AppBuild
from services.ai_device_lab.intake import (
    ApproveScenario,
    CompleteGeneration,
    approve_scenario,
    complete_generation,
    scenario_version_content_hash,
    start_generation,
)
from services.ai_device_lab.readiness import ReadinessPolicy, StartCampaign, start_campaign
from services.ai_device_lab.service_campaigns import (
    CreateServiceCampaign,
    create_service_campaign,
)
from services.ai_device_lab.wizard import (
    SaveWizardDraft,
    WizardDraftInput,
    WizardNotFound,
    WizardRevisionConflict,
    WizardInvariantError,
    load_wizard_state,
    run_wizard_generation,
    save_wizard_draft,
    wizard_operation_policy,
)
from services.operation_policy import OperationPolicy
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, ORG_B, USER_A, seed_two_org_fixture


def _draft(*, goal: str = "Open the app and verify Home") -> WizardDraftInput:
    return WizardDraftInput(
        package_name="com.example.app",
        closed_track_link="https://play.google.com/store/apps/details?id=com.example.app",
        test_goal=goal,
        test_environment={"locale": "en-US", "network": "wifi"},
        version_name="1.0.0",
        version_code="100",
        source_kind="closed_track",
        source_ref="play-closed-track",
        checksum_sha256=None,
    )


def _policy() -> OperationPolicy:
    return OperationPolicy(
        version="adl-operations-v1",
        app_package="com.example.app",
        allowed_actions=frozenset({"navigation.open"}),
        allowed_targets=frozenset({"com.example.app"}),
    )


async def _campaign(db, runtime_campaign_id: str):
    return await create_service_campaign(
        db,
        CreateServiceCampaign(
            org_id=ORG_A,
            owner_id=USER_A,
            runtime_campaign_id=runtime_campaign_id,
            package_name="com.example.app",
            timezone="UTC",
            plan_version="adl-14d-v1",
        ),
    )


@pytest.mark.asyncio
async def test_wizard_reuses_one_legacy_duplicate_build_deterministically(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _campaign(db, seeded["campaign_a"])
            duplicates = [
                AppBuild(
                    org_id=ORG_A,
                    package_name="com.example.app",
                    version_name="1.0.0",
                    version_code="100",
                    source_kind="closed_track",
                    source_ref="play-closed-track",
                    checksum_sha256=None,
                )
                for _ in range(2)
            ]
            db.add_all(duplicates)
            await db.flush()

            intake = await save_wizard_draft(
                db,
                SaveWizardDraft(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    service_campaign_id=campaign.id,
                    expected_revision=0,
                    draft=_draft(),
                ),
            )

    assert intake.requested_build_id == duplicates[0].id


@pytest.mark.asyncio
async def test_wizard_draft_survives_reload_and_rejects_stale_revision(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _campaign(db, seeded["campaign_a"])
            command = SaveWizardDraft(
                org_id=ORG_A,
                owner_id=USER_A,
                service_campaign_id=campaign.id,
                expected_revision=0,
                draft=_draft(),
            )
            first = await save_wizard_draft(db, command)
            replay = await save_wizard_draft(db, command)
            changed = await save_wizard_draft(
                db,
                SaveWizardDraft(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    service_campaign_id=campaign.id,
                    expected_revision=0,
                    draft=_draft(goal="Verify Settings"),
                ),
            )
            with pytest.raises(WizardRevisionConflict) as stale:
                await save_wizard_draft(
                    db,
                    SaveWizardDraft(
                        org_id=ORG_A,
                        owner_id=USER_A,
                        service_campaign_id=campaign.id,
                        expected_revision=0,
                        draft=_draft(goal="Verify Profile"),
                    ),
                )
            await db.commit()

            state = await load_wizard_state(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
            )

    assert replay.id == first.id
    assert changed.id == first.id
    assert changed.lock_version == 1
    assert stale.value.current_revision == 1
    assert state.intake is not None
    assert state.intake.test_goal == "Verify Settings"
    assert state.current_step == "scenario"
    assert state.payment.provider_configured is False
    assert state.payment.blocker_code == "APPROVED_SCENARIO_REQUIRED"


@pytest.mark.asyncio
async def test_edit_after_approval_invalidates_active_approval_and_readiness(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _campaign(db, seeded["campaign_a"])
            intake = await save_wizard_draft(
                db,
                SaveWizardDraft(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    service_campaign_id=campaign.id,
                    expected_revision=0,
                    draft=_draft(),
                ),
            )
            operation = await start_generation(
                db,
                intake_id=intake.id,
                org_id=ORG_A,
                operation_id="wizard-generation-1",
            )
            version = await complete_generation(
                db,
                CompleteGeneration(
                    org_id=ORG_A,
                    operation_id=operation.operation_id,
                    scenario_name="Safe home check",
                    scenario={
                        "steps": [
                            {
                                "type": "launch_app",
                                "package": "com.example.app",
                                "semantic_action": "navigation.open",
                                "policy_target": "com.example.app",
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
            approved_state = await load_wizard_state(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
            )

            await save_wizard_draft(
                db,
                SaveWizardDraft(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    service_campaign_id=campaign.id,
                    expected_revision=0,
                    draft=_draft(goal="Verify the new profile journey"),
                ),
            )
            edited_state = await load_wizard_state(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
            )
            readiness = await start_campaign(
                db,
                StartCampaign(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="wizard-readiness-after-edit",
                    now=approval.approved_at,
                    policy=ReadinessPolicy(version="adl-readiness-v1"),
                ),
            )

    approval_check = next(
        check for check in readiness.checks if check.check_key == "scenario_approval"
    )
    assert approved_state.approval is not None
    assert edited_state.approval is None
    assert edited_state.generation is None
    assert edited_state.current_step == "scenario"
    assert approval_check.status == "blocked"
    assert approval_check.reason_code == "APPROVED_SCENARIO_REQUIRED"


@pytest.mark.asyncio
async def test_wizard_state_is_tenant_scoped(tenancy_session_factory) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _campaign(db, seeded["campaign_a"])
            await db.commit()

    with tenant_context(ORG_B):
        async with tenancy_session_factory() as db:
            with pytest.raises(WizardNotFound):
                await load_wizard_state(
                    db,
                    org_id=ORG_B,
                    service_campaign_id=campaign.id,
                )


@pytest.mark.asyncio
async def test_provider_failure_is_persisted_and_retry_does_not_duplicate_call(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    calls = 0

    def unavailable(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("fixture provider unavailable")

    monkeypatch.setattr(
        "runtime.ai.ai_client.build_scenario_from_instructions",
        unavailable,
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _campaign(db, seeded["campaign_a"])
            await save_wizard_draft(
                db,
                SaveWizardDraft(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    service_campaign_id=campaign.id,
                    expected_revision=0,
                    draft=_draft(),
                ),
            )
            first = await run_wizard_generation(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                operation_id="provider-outage-fixture",
            )
            replay = await run_wizard_generation(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                operation_id="provider-outage-fixture",
            )

    assert first.id == replay.id
    assert replay.status == "failed"
    assert replay.error_code == "AI_PROVIDER_UNAVAILABLE"
    assert calls == 1


@pytest.mark.asyncio
async def test_sensitive_provider_context_is_rejected_before_persistence(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _campaign(db, seeded["campaign_a"])
            unsafe = _draft()
            unsafe = WizardDraftInput(
                package_name=unsafe.package_name,
                closed_track_link=unsafe.closed_track_link,
                test_goal=unsafe.test_goal,
                test_environment={"locale": "en-US", "api_token": "must-not-leave"},
                version_name=unsafe.version_name,
                version_code=unsafe.version_code,
                source_kind=unsafe.source_kind,
                source_ref=unsafe.source_ref,
                checksum_sha256=unsafe.checksum_sha256,
            )
            with pytest.raises(WizardInvariantError) as rejected:
                await save_wizard_draft(
                    db,
                    SaveWizardDraft(
                        org_id=ORG_A,
                        owner_id=USER_A,
                        service_campaign_id=campaign.id,
                        expected_revision=0,
                        draft=unsafe,
                    ),
                )

    assert rejected.value.code == "SENSITIVE_TEST_ENVIRONMENT_REJECTED"
    assert wizard_operation_policy("com.example.app").allowed_actions == frozenset(
        {"navigation.open"}
    )


@pytest.mark.asyncio
async def test_new_operation_id_reuses_fresh_running_generation(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)

    def must_not_run(*args, **kwargs):
        raise AssertionError("provider must not run for an already-running intake")

    monkeypatch.setattr(
        "runtime.ai.ai_client.build_scenario_from_instructions",
        must_not_run,
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await _campaign(db, seeded["campaign_a"])
            intake = await save_wizard_draft(
                db,
                SaveWizardDraft(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    service_campaign_id=campaign.id,
                    expected_revision=0,
                    draft=_draft(),
                ),
            )
            running = await start_generation(
                db,
                intake_id=intake.id,
                org_id=ORG_A,
                operation_id="running-generation-original",
            )
            replay = await run_wizard_generation(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                operation_id="running-generation-other-tab",
            )

    assert replay.id == running.id
    assert replay.status == "running"
