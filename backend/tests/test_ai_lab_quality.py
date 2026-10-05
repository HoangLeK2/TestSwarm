from __future__ import annotations

import pytest

from db.models.ai_device_lab import AppBuild, RunAttempt
from services.ai_device_lab.quality import (
    CreateIssue,
    QualityInvariantError,
    RequestRetest,
    create_issue,
    evaluate_retest,
    request_retest,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


def _attempt(attempt_id: str, build_id: str, outcome: str, key: str) -> RunAttempt:
    return RunAttempt(
        id=attempt_id,
        org_id=ORG_A,
        service_campaign_id="service-quality-1",
        lane_id="lane-quality-1",
        slot_id="slot-quality-1",
        attempt_no=1 if "source" in attempt_id else 2,
        execution_id=f"execution-{attempt_id}",
        scenario_version_id="scenario-quality-1",
        app_build_id=build_id,
        idempotency_key=key,
        reason="retest" if "new" in attempt_id else "scheduled",
        status="finished",
        outcome=outcome,
    )


@pytest.mark.asyncio
async def test_retest_is_idempotent_and_only_matching_assertion_build_can_mark_fixed(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            v1 = AppBuild(
                id="build-quality-v1",
                org_id=ORG_A,
                package_name="com.example.app",
                version_name="1",
                version_code="1",
                source_kind="artifact",
                checksum_sha256="1" * 64,
            )
            v2 = AppBuild(
                id="build-quality-v2",
                org_id=ORG_A,
                package_name="com.example.app",
                version_name="2",
                version_code="2",
                source_kind="artifact",
                checksum_sha256="2" * 64,
            )
            source = _attempt("source-attempt", v1.id, "fail", "source-key")
            db.add_all([v1, v2, source])
            await db.flush()
            issue = await create_issue(
                db,
                CreateIssue(
                    org_id=ORG_A,
                    source_attempt_id=source.id,
                    severity="major",
                    assertion_key="home-title-visible",
                    expected="Home title",
                    actual="Blank screen",
                    reproduction={"step_path": "steps[4]"},
                    created_by=USER_A,
                ),
            )
            command = RequestRetest(
                org_id=ORG_A,
                issue_id=issue.id,
                target_build_id=v2.id,
                target_scenario_version_id="scenario-quality-1",
                lane_scope=("lane-quality-1",),
                idempotency_key="retest-key-1",
                consent_snapshot={"accepted": True, "device_minutes": 15, "price_minor": 0},
                requested_by=USER_A,
            )
            first = await request_retest(db, command)
            second = await request_retest(db, command)
            with pytest.raises(QualityInvariantError, match="retest idempotency key"):
                await request_retest(
                    db,
                    RequestRetest(
                        org_id=ORG_A,
                        issue_id=issue.id,
                        target_build_id=v1.id,
                        target_scenario_version_id="scenario-quality-1",
                        lane_scope=("lane-quality-1",),
                        idempotency_key="retest-key-1",
                        consent_snapshot={"accepted": True, "device_minutes": 15, "price_minor": 0},
                        requested_by=USER_A,
                    ),
                )
            passing = _attempt("new-attempt", v2.id, "pass", "new-key")
            db.add(passing)
            await db.flush()
            evaluated = await evaluate_retest(
                db,
                org_id=ORG_A,
                retest_request_id=first.id,
                new_attempt_id=passing.id,
                assertion_key="home-title-visible",
                actor_id=USER_A,
            )

    assert first.id == second.id
    assert evaluated.verdict == "fixed"
    assert evaluated.verdict_reason == "MATCHING_ASSERTION_PASSED"
    assert issue.status == "fixed"
