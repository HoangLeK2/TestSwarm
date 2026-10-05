from __future__ import annotations

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab import (
    AppBuild,
    ScenarioApproval,
    ScenarioGenerationOperation,
)
from db.models.scenario_version import ScenarioVersion
from services.ai_device_lab.intake import (
    ApproveScenario,
    CompleteGeneration,
    CreateIntake,
    IntakeInvariantError,
    ScenarioGenerationRejected,
    complete_generation,
    create_intake,
    approve_scenario,
    authorize_approved_scenario,
    scenario_version_content_hash,
    start_generation,
)
from services.operation_policy import OperationPolicy
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


def test_generation_operation_has_tenant_candidate_key_for_approval_fk() -> None:
    tenant_keys = {
        tuple(column.name for column in constraint.columns)
        for constraint in ScenarioGenerationOperation.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("org_id", "id") in tenant_keys


def _policy() -> OperationPolicy:
    return OperationPolicy(
        version="adl-operations-v1",
        app_package="com.example.app",
        allowed_actions=frozenset({"navigation.open", "ui.tap"}),
        allowed_targets=frozenset({"com.example.app", "home"}),
    )


@pytest.mark.asyncio
async def test_generation_operation_id_cannot_be_rebound_to_another_intake(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            build = AppBuild(
                org_id=ORG_A,
                package_name="com.example.app",
                version_name="1.0",
                version_code="1",
                source_kind="uploaded_artifact",
                checksum_sha256="e" * 64,
            )
            db.add(build)
            await db.flush()
            intakes = []
            for suffix in ("one", "two"):
                intakes.append(
                    await create_intake(
                        db,
                        CreateIntake(
                            org_id=ORG_A,
                            owner_id=USER_A,
                            runtime_campaign_id=seeded["campaign_a"],
                            requested_build_id=build.id,
                            package_name="com.example.app",
                            closed_track_link="https://play.google.com/store/apps/details?id=com.example.app",
                            test_goal=f"Verify home {suffix}",
                            test_environment={"locale": "en-US"},
                        ),
                    )
                )
            operation = await start_generation(
                db,
                intake_id=intakes[0].id,
                org_id=ORG_A,
                operation_id="generation-stable-key",
            )
            repeated = await start_generation(
                db,
                intake_id=intakes[0].id,
                org_id=ORG_A,
                operation_id="generation-stable-key",
            )
            with pytest.raises(IntakeInvariantError, match="another intake"):
                await start_generation(
                    db,
                    intake_id=intakes[1].id,
                    org_id=ORG_A,
                    operation_id="generation-stable-key",
                )

    assert repeated.id == operation.id


@pytest.mark.asyncio
async def test_generated_purchase_is_failed_without_persisting_a_version(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            build = AppBuild(
                org_id=ORG_A,
                package_name="com.example.app",
                version_name="1.0",
                version_code="1",
                source_kind="uploaded_artifact",
                checksum_sha256="b" * 64,
            )
            db.add(build)
            await db.flush()
            intake = await create_intake(
                db,
                CreateIntake(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    requested_build_id=build.id,
                    package_name="com.example.app",
                    closed_track_link="https://play.google.com/store/apps/details?id=com.example.app",
                    test_goal="Verify the home journey without purchases",
                    test_environment={"locale": "en-US"},
                ),
            )
            operation = await start_generation(
                db,
                intake_id=intake.id,
                org_id=ORG_A,
                operation_id="generate-1",
            )

            with pytest.raises(ScenarioGenerationRejected) as rejected:
                await complete_generation(
                    db,
                    CompleteGeneration(
                        org_id=ORG_A,
                        operation_id=operation.operation_id,
                        scenario_name="Unsafe purchase",
                        scenario={
                            "steps": [
                                {
                                    "type": "launch_app",
                                    "package": "com.example.app",
                                },
                                {
                                    "type": "tap_selector",
                                    "semantic_action": "commerce.purchase",
                                    "policy_target": "buy-now",
                                    "selector": {"by": "text", "value": "Buy now"},
                                },
                                {
                                    "type": "assert_element",
                                    "selector": {"by": "text", "value": "Receipt"},
                                    "timeout": 5,
                                },
                            ]
                        },
                        policy=_policy(),
                    ),
                )
            await db.commit()

            version_count = await db.scalar(
                select(func.count()).select_from(ScenarioVersion)
            )
            refreshed = await db.get(ScenarioGenerationOperation, operation.id)

    assert rejected.value.reason_code == "FORBIDDEN_ACTION"
    assert version_count == 0
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.error_code == "FORBIDDEN_ACTION"


@pytest.mark.asyncio
async def test_approval_pins_exact_content_and_policy_version(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            build = AppBuild(
                org_id=ORG_A,
                package_name="com.example.app",
                version_name="1.1",
                version_code="2",
                source_kind="uploaded_artifact",
                checksum_sha256="c" * 64,
            )
            db.add(build)
            await db.flush()
            intake = await create_intake(
                db,
                CreateIntake(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    requested_build_id=build.id,
                    package_name="com.example.app",
                    closed_track_link="https://play.google.com/store/apps/details?id=com.example.app",
                    test_goal="Open the app and verify Home",
                    test_environment={"locale": "en-US"},
                ),
            )
            operation = await start_generation(
                db,
                intake_id=intake.id,
                org_id=ORG_A,
                operation_id="generate-safe-1",
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
                    provider_request_ref="provider-request-redacted-1",
                ),
            )
            content_hash = scenario_version_content_hash(version)
            approval = await approve_scenario(
                db,
                ApproveScenario(
                    org_id=ORG_A,
                    operation_id=operation.operation_id,
                    scenario_version_id=version.id,
                    expected_content_hash=content_hash,
                    approved_by=USER_A,
                    policy=_policy(),
                ),
            )
            authorized = await authorize_approved_scenario(
                db,
                org_id=ORG_A,
                approval_id=approval.id,
                scenario_version_id=version.id,
                active_policy=_policy(),
            )
            await db.commit()

    assert isinstance(approval, ScenarioApproval)
    assert approval.content_hash == content_hash
    assert approval.policy_version == "adl-operations-v1"
    assert approval.allowed_operations == ["navigation.open"]
    assert authorized.id == version.id


@pytest.mark.asyncio
async def test_authorization_rejects_stale_policy_and_changed_snapshot(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            build = AppBuild(
                org_id=ORG_A,
                package_name="com.example.app",
                version_name="1.2",
                version_code="3",
                source_kind="uploaded_artifact",
                checksum_sha256="d" * 64,
            )
            db.add(build)
            await db.flush()
            intake = await create_intake(
                db,
                CreateIntake(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    requested_build_id=build.id,
                    package_name="com.example.app",
                    closed_track_link="https://play.google.com/store/apps/details?id=com.example.app",
                    test_goal="Verify the nested home assertion",
                    test_environment={"locale": "en-US"},
                ),
            )
            operation = await start_generation(
                db,
                intake_id=intake.id,
                org_id=ORG_A,
                operation_id="generate-safe-2",
            )
            scenario = {
                "steps": [
                    {
                        "type": "launch_app",
                        "package": "com.example.app",
                        "semantic_action": "navigation.open",
                        "policy_target": "com.example.app",
                    },
                    {
                        "type": "if_element",
                        "by": "text",
                        "value": "Home",
                        "then": [
                            {
                                "type": "assert_element",
                                "by": "text",
                                "value": "Home",
                            }
                        ],
                    },
                ]
            }
            version = await complete_generation(
                db,
                CompleteGeneration(
                    org_id=ORG_A,
                    operation_id=operation.operation_id,
                    scenario_name="Nested safe check",
                    scenario=scenario,
                    policy=_policy(),
                ),
            )
            replayed = await complete_generation(
                db,
                CompleteGeneration(
                    org_id=ORG_A,
                    operation_id=operation.operation_id,
                    scenario_name="Nested safe check",
                    scenario=scenario,
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

            stale_policy = OperationPolicy(
                version="adl-operations-v2",
                app_package="com.example.app",
                allowed_actions=frozenset({"navigation.open", "ui.tap"}),
                allowed_targets=frozenset({"com.example.app", "home"}),
            )
            with pytest.raises(ScenarioGenerationRejected) as stale:
                await authorize_approved_scenario(
                    db,
                    org_id=ORG_A,
                    approval_id=approval.id,
                    scenario_version_id=version.id,
                    active_policy=stale_policy,
                )

            version.steps = [
                *version.steps,
                {"type": "wait", "seconds": 1},
            ]
            await db.flush()
            with pytest.raises(ScenarioGenerationRejected) as changed:
                await authorize_approved_scenario(
                    db,
                    org_id=ORG_A,
                    approval_id=approval.id,
                    scenario_version_id=version.id,
                    active_policy=_policy(),
                )

    assert replayed.id == version.id
    assert stale.value.reason_code == "STALE_POLICY_APPROVAL"
    assert changed.value.reason_code == "APPROVED_CONTENT_MISMATCH"
