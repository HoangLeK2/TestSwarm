from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.ai_device_lab.acceptance import (
    REQUIRED_ADL_IDS,
    AcceptanceInvariantError,
    BuildAcceptanceCandidate,
    RequirementEvidence,
    build_acceptance_candidate,
    evaluate_acceptance_candidate,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


def _requirement(adl_id: str, *, status: str = "pass") -> RequirementEvidence:
    return RequirementEvidence(
        requirement_key=f"{adl_id}:AC1:T1",
        adl_id=adl_id,
        acceptance_id="AC1",
        test_id=f"{adl_id.removeprefix('ADL-')}-T1",
        expected="documented acceptance behavior",
        observed="fixture verification only",
        status=status,
        required_evidence_level="source",
        observed_evidence_level="source",
        evidence_refs=(f"private://fixture/{adl_id}",),
        reviewer_id="fixture-reviewer",
        executed_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_complete_fixture_pack_remains_no_go_and_never_claims_launch(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            candidate = await build_acceptance_candidate(
                db,
                BuildAcceptanceCandidate(
                    org_id=ORG_A,
                    version="fixture-candidate-v1",
                    source_kind="fixture",
                    environment="sqlite-test",
                    commit_sha="fixture-commit",
                    schema_version="154",
                    rollback_owner="fixture-rollback-owner",
                    oncall_owner="fixture-oncall-owner",
                    created_by=USER_A,
                    frozen_at=now,
                    requirements=tuple(_requirement(adl_id) for adl_id in sorted(REQUIRED_ADL_IDS)),
                ),
            )
            repeated_candidate = await build_acceptance_candidate(
                db,
                BuildAcceptanceCandidate(
                    org_id=ORG_A,
                    version="fixture-candidate-v1",
                    source_kind="fixture",
                    environment="sqlite-test",
                    commit_sha="fixture-commit",
                    schema_version="154",
                    rollback_owner="fixture-rollback-owner",
                    oncall_owner="fixture-oncall-owner",
                    created_by=USER_A,
                    frozen_at=now,
                    requirements=tuple(_requirement(adl_id) for adl_id in sorted(REQUIRED_ADL_IDS)),
                ),
            )
            changed = tuple(
                _requirement(adl_id, status="fail" if adl_id == "ADL-21" else "pass")
                for adl_id in sorted(REQUIRED_ADL_IDS)
            )
            with pytest.raises(AcceptanceInvariantError, match="immutable"):
                await build_acceptance_candidate(
                    db,
                    BuildAcceptanceCandidate(
                        org_id=ORG_A,
                        version="fixture-candidate-v1",
                        source_kind="fixture",
                        environment="sqlite-test",
                        commit_sha="fixture-commit",
                        schema_version="154",
                        rollback_owner="fixture-rollback-owner",
                        oncall_owner="fixture-oncall-owner",
                        created_by=USER_A,
                        frozen_at=now,
                        requirements=changed,
                    ),
                )
            decision = await evaluate_acceptance_candidate(
                db,
                org_id=ORG_A,
                candidate_id=candidate.id,
                evaluation_key="fixture-evaluation-v1",
                evaluated_at=now,
            )
            repeated = await evaluate_acceptance_candidate(
                db,
                org_id=ORG_A,
                candidate_id=candidate.id,
                evaluation_key="fixture-evaluation-v1",
                evaluated_at=now,
            )

    assert repeated_candidate.id == candidate.id
    assert repeated.id == decision.id
    assert decision.verdict == "no_go"
    assert decision.requirement_summary["covered_task_count"] == 28
    assert decision.requirement_summary["pass_count"] == 28
    assert decision.blockers == [{"code": "FIXTURE_CANDIDATE_CANNOT_LAUNCH"}]
    assert len(decision.pack_sha256) == 64


@pytest.mark.asyncio
async def test_incomplete_pack_lists_missing_task_evidence_and_review_blockers(
    tenancy_session_factory,
) -> None:
    await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    incomplete = RequirementEvidence(
        requirement_key="ADL-01:AC1:01-T1",
        adl_id="ADL-01",
        acceptance_id="AC1",
        test_id="01-T1",
        expected="real phone execution evidence",
        observed="source test only",
        status="blocked",
        required_evidence_level="live",
        observed_evidence_level="source",
        evidence_refs=(),
        reviewer_id=None,
        executed_at=None,
        blocker="permitted phone not available",
    )
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            candidate = await build_acceptance_candidate(
                db,
                BuildAcceptanceCandidate(
                    org_id=ORG_A,
                    version="incomplete-candidate-v1",
                    source_kind="fixture",
                    environment="sqlite-test",
                    commit_sha="fixture-commit",
                    schema_version="154",
                    rollback_owner=None,
                    oncall_owner=None,
                    created_by=USER_A,
                    frozen_at=now,
                    requirements=(incomplete,),
                ),
            )
            decision = await evaluate_acceptance_candidate(
                db,
                org_id=ORG_A,
                candidate_id=candidate.id,
                evaluation_key="incomplete-evaluation-v1",
                evaluated_at=now,
            )

    codes = {blocker["code"] for blocker in decision.blockers}
    assert decision.verdict == "no_go"
    assert decision.requirement_summary["covered_task_count"] == 1
    assert "MISSING_TASK" in codes
    assert "REQUIREMENT_NOT_PASS" in codes
    assert "INSUFFICIENT_EVIDENCE_LEVEL" in codes
    assert "MISSING_EVIDENCE_REF" in codes
    assert "PENDING_REVIEW" in codes
    assert "UNRESOLVED_BLOCKER" in codes
    assert "ROLLBACK_OWNER_REQUIRED" in codes
    assert "ONCALL_OWNER_REQUIRED" in codes
