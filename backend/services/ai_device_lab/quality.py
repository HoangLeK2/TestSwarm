"""Issue creation and assertion-based retest verdicts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import AppBuild, RunAttempt
from db.models.ai_device_lab_quality import AppIssue, IssueTransition, RetestRequest


class QualityInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CreateIssue:
    org_id: str
    source_attempt_id: str
    severity: str
    assertion_key: str
    expected: str
    actual: str
    reproduction: dict
    created_by: str


@dataclass(frozen=True, slots=True)
class RequestRetest:
    org_id: str
    issue_id: str
    target_build_id: str
    target_scenario_version_id: str
    lane_scope: tuple[str, ...]
    idempotency_key: str
    consent_snapshot: dict
    requested_by: str


async def create_issue(db: AsyncSession, command: CreateIssue) -> AppIssue:
    attempt = (
        await db.execute(
            select(RunAttempt).where(
                RunAttempt.id == command.source_attempt_id,
                RunAttempt.org_id == command.org_id,
            )
        )
    ).scalar_one_or_none()
    if attempt is None or attempt.outcome != "fail":
        raise QualityInvariantError("issues require a failed evaluated attempt")
    fingerprint_payload = {
        "build_id": attempt.app_build_id,
        "scenario_version_id": attempt.scenario_version_id,
        "assertion_key": command.assertion_key,
        "expected": command.expected,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    issue = AppIssue(
        org_id=command.org_id,
        service_campaign_id=attempt.service_campaign_id,
        source_attempt_id=attempt.id,
        source_build_id=attempt.app_build_id,
        source_scenario_version_id=attempt.scenario_version_id,
        severity=command.severity,
        assertion_key=command.assertion_key,
        expected=command.expected,
        actual=command.actual,
        reproduction=command.reproduction,
        fingerprint=fingerprint,
        status="open",
        created_by=command.created_by,
    )
    db.add(issue)
    await db.flush()
    return issue


async def request_retest(db: AsyncSession, command: RequestRetest) -> RetestRequest:
    existing = (
        await db.execute(
            select(RetestRequest).where(
                RetestRequest.org_id == command.org_id,
                RetestRequest.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.issue_id != command.issue_id
            or existing.target_build_id != command.target_build_id
            or existing.target_scenario_version_id != command.target_scenario_version_id
            or existing.lane_scope != list(command.lane_scope)
            or existing.consent_snapshot != command.consent_snapshot
            or existing.requested_by != command.requested_by
        ):
            raise QualityInvariantError("retest idempotency key was reused with different input")
        return existing
    issue = (
        await db.execute(
            select(AppIssue).where(AppIssue.id == command.issue_id, AppIssue.org_id == command.org_id)
        )
    ).scalar_one_or_none()
    build = (
        await db.execute(
            select(AppBuild).where(AppBuild.id == command.target_build_id, AppBuild.org_id == command.org_id)
        )
    ).scalar_one_or_none()
    if issue is None or build is None:
        raise QualityInvariantError("issue/build is outside retest scope")
    if not command.consent_snapshot.get("accepted"):
        raise QualityInvariantError("retest quota/cost consent is required")
    request = RetestRequest(
        org_id=command.org_id,
        issue_id=issue.id,
        source_attempt_id=issue.source_attempt_id,
        target_build_id=build.id,
        target_scenario_version_id=command.target_scenario_version_id,
        lane_scope=list(command.lane_scope),
        idempotency_key=command.idempotency_key,
        consent_snapshot=command.consent_snapshot,
        status="requested",
        requested_by=command.requested_by,
    )
    db.add(request)
    await db.flush()
    return request


async def evaluate_retest(
    db: AsyncSession,
    *,
    org_id: str,
    retest_request_id: str,
    new_attempt_id: str,
    assertion_key: str | None,
    actor_id: str,
) -> RetestRequest:
    request = (
        await db.execute(
            select(RetestRequest)
            .where(RetestRequest.id == retest_request_id, RetestRequest.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise QualityInvariantError("retest request not found")
    issue = await db.get(AppIssue, request.issue_id)
    attempt = (
        await db.execute(
            select(RunAttempt).where(RunAttempt.id == new_attempt_id, RunAttempt.org_id == org_id)
        )
    ).scalar_one_or_none()
    if issue is None or attempt is None:
        raise QualityInvariantError("retest lineage is incomplete")
    request.new_attempt_id = attempt.id
    if attempt.app_build_id != request.target_build_id:
        verdict, reason = "inconclusive", "OBSERVED_BUILD_MISMATCH"
    elif assertion_key != issue.assertion_key:
        verdict, reason = "inconclusive", "ASSERTION_SCOPE_MISMATCH"
    elif attempt.outcome == "pass":
        verdict, reason = "fixed", "MATCHING_ASSERTION_PASSED"
    elif attempt.outcome == "fail":
        verdict, reason = "still_failing", "MATCHING_ASSERTION_FAILED"
    else:
        verdict, reason = "inconclusive", "RETEST_NOT_EVALUATED"
    request.status = "completed"
    request.verdict = verdict
    request.verdict_reason = reason
    if verdict == "fixed":
        previous = issue.status
        issue.status = "fixed"
        db.add(
            IssueTransition(
                org_id=org_id,
                issue_id=issue.id,
                from_status=previous,
                to_status="fixed",
                actor_id=actor_id,
                reason=reason,
            )
        )
    await db.flush()
    return request
