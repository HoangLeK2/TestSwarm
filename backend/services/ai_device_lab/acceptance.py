"""Fail-closed launch acceptance pack assembly and evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab_acceptance import (
    AcceptanceCandidate,
    AcceptanceDecision,
    AcceptanceRequirement,
)


class AcceptanceInvariantError(ValueError):
    pass


REQUIRED_ADL_IDS = frozenset(
    {
        "ADL-00",
        "ADL-01",
        "ADL-02",
        "ADL-03a",
        "ADL-03b",
        "ADL-04",
        "ADL-05",
        "ADL-06",
        "ADL-07",
        "ADL-08",
        "ADL-09",
        "ADL-10",
        "ADL-11",
        "ADL-12",
        "ADL-13a",
        "ADL-13b",
        "ADL-14",
        "ADL-15",
        "ADL-16",
        "ADL-17",
        "ADL-18a",
        "ADL-18b",
        "ADL-19a",
        "ADL-19b",
        "ADL-20a",
        "ADL-20b",
        "ADL-20c",
        "ADL-21",
    }
)
EVIDENCE_RANK = {"source": 0, "mock": 1, "sandbox": 2, "live": 3}


@dataclass(frozen=True, slots=True)
class RequirementEvidence:
    requirement_key: str
    adl_id: str
    acceptance_id: str
    test_id: str
    expected: str
    observed: str
    status: str
    required_evidence_level: str
    observed_evidence_level: str
    evidence_refs: tuple[str, ...]
    reviewer_id: str | None
    executed_at: datetime | None
    blocker: str | None = None


@dataclass(frozen=True, slots=True)
class BuildAcceptanceCandidate:
    org_id: str
    version: str
    source_kind: str
    environment: str
    commit_sha: str
    schema_version: str
    rollback_owner: str | None
    oncall_owner: str | None
    created_by: str
    frozen_at: datetime
    requirements: tuple[RequirementEvidence, ...]


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def build_acceptance_candidate(
    db: AsyncSession,
    command: BuildAcceptanceCandidate,
) -> AcceptanceCandidate:
    manifest_payload = {
        "version": command.version,
        "source_kind": command.source_kind,
        "environment": command.environment,
        "commit_sha": command.commit_sha,
        "schema_version": command.schema_version,
        "rollback_owner": command.rollback_owner,
        "oncall_owner": command.oncall_owner,
        "requirements": [
            {
                "requirement_key": item.requirement_key,
                "adl_id": item.adl_id,
                "acceptance_id": item.acceptance_id,
                "test_id": item.test_id,
                "expected": item.expected,
                "observed": item.observed,
                "status": item.status,
                "required_evidence_level": item.required_evidence_level,
                "observed_evidence_level": item.observed_evidence_level,
                "evidence_refs": list(item.evidence_refs),
                "reviewer_id": item.reviewer_id,
                "executed_at": item.executed_at.isoformat() if item.executed_at else None,
                "blocker": item.blocker,
            }
            for item in sorted(command.requirements, key=lambda value: value.requirement_key)
        ],
    }
    manifest_sha256 = _digest(manifest_payload)
    existing = (
        await db.execute(
            select(AcceptanceCandidate).where(
                AcceptanceCandidate.org_id == command.org_id,
                AcceptanceCandidate.version == command.version,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.manifest_sha256 != manifest_sha256:
            raise AcceptanceInvariantError("acceptance candidate version is immutable")
        return existing
    if command.source_kind not in {"fixture", "real"}:
        raise AcceptanceInvariantError("candidate source must be fixture or real")
    keys = [item.requirement_key for item in command.requirements]
    if len(keys) != len(set(keys)):
        raise AcceptanceInvariantError("acceptance requirement keys must be unique")
    for item in command.requirements:
        if item.status not in {"pass", "fail", "blocked", "not_run"}:
            raise AcceptanceInvariantError("unsupported acceptance status")
        if item.required_evidence_level not in EVIDENCE_RANK or item.observed_evidence_level not in EVIDENCE_RANK:
            raise AcceptanceInvariantError("unsupported evidence level")
    candidate = AcceptanceCandidate(
        org_id=command.org_id,
        version=command.version,
        source_kind=command.source_kind,
        environment=command.environment,
        commit_sha=command.commit_sha,
        schema_version=command.schema_version,
        manifest_sha256=manifest_sha256,
        status="frozen",
        rollback_owner=command.rollback_owner,
        oncall_owner=command.oncall_owner,
        created_by=command.created_by,
        frozen_at=command.frozen_at,
    )
    db.add(candidate)
    await db.flush()
    db.add_all(
        [
            AcceptanceRequirement(
                org_id=command.org_id,
                candidate_id=candidate.id,
                requirement_key=item.requirement_key,
                adl_id=item.adl_id,
                acceptance_id=item.acceptance_id,
                test_id=item.test_id,
                expected=item.expected,
                observed=item.observed,
                status=item.status,
                required_evidence_level=item.required_evidence_level,
                observed_evidence_level=item.observed_evidence_level,
                evidence_refs=list(item.evidence_refs),
                reviewer_id=item.reviewer_id,
                executed_at=item.executed_at,
                blocker=item.blocker,
            )
            for item in command.requirements
        ]
    )
    await db.flush()
    return candidate


async def evaluate_acceptance_candidate(
    db: AsyncSession,
    *,
    org_id: str,
    candidate_id: str,
    evaluation_key: str,
    evaluated_at: datetime,
) -> AcceptanceDecision:
    existing = (
        await db.execute(
            select(AcceptanceDecision).where(
                AcceptanceDecision.org_id == org_id,
                AcceptanceDecision.candidate_id == candidate_id,
                AcceptanceDecision.evaluation_key == evaluation_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    candidate = (
        await db.execute(
            select(AcceptanceCandidate)
            .where(
                AcceptanceCandidate.id == candidate_id,
                AcceptanceCandidate.org_id == org_id,
                AcceptanceCandidate.status.in_(("frozen", "evaluated")),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise AcceptanceInvariantError("frozen acceptance candidate not found")
    requirements = list(
        (
            await db.execute(
                select(AcceptanceRequirement)
                .where(
                    AcceptanceRequirement.org_id == org_id,
                    AcceptanceRequirement.candidate_id == candidate.id,
                )
                .order_by(AcceptanceRequirement.requirement_key)
            )
        ).scalars()
    )
    blockers: list[dict] = []
    covered = {row.adl_id for row in requirements}
    for adl_id in sorted(REQUIRED_ADL_IDS - covered):
        blockers.append({"code": "MISSING_TASK", "adl_id": adl_id})
    for row in requirements:
        if row.status != "pass":
            blockers.append(
                {
                    "code": "REQUIREMENT_NOT_PASS",
                    "requirement_key": row.requirement_key,
                    "status": row.status,
                }
            )
        if EVIDENCE_RANK[row.observed_evidence_level] < EVIDENCE_RANK[row.required_evidence_level]:
            blockers.append(
                {
                    "code": "INSUFFICIENT_EVIDENCE_LEVEL",
                    "requirement_key": row.requirement_key,
                    "required": row.required_evidence_level,
                    "observed": row.observed_evidence_level,
                }
            )
        if not row.evidence_refs:
            blockers.append({"code": "MISSING_EVIDENCE_REF", "requirement_key": row.requirement_key})
        if not row.reviewer_id:
            blockers.append({"code": "PENDING_REVIEW", "requirement_key": row.requirement_key})
        if row.blocker:
            blockers.append(
                {"code": "UNRESOLVED_BLOCKER", "requirement_key": row.requirement_key, "detail": row.blocker}
            )
    if candidate.source_kind != "real":
        blockers.append({"code": "FIXTURE_CANDIDATE_CANNOT_LAUNCH"})
    if not candidate.rollback_owner:
        blockers.append({"code": "ROLLBACK_OWNER_REQUIRED"})
    if not candidate.oncall_owner:
        blockers.append({"code": "ONCALL_OWNER_REQUIRED"})
    summary = {
        "required_task_count": len(REQUIRED_ADL_IDS),
        "covered_task_count": len(covered & REQUIRED_ADL_IDS),
        "requirement_count": len(requirements),
        "pass_count": sum(row.status == "pass" for row in requirements),
        "fail_count": sum(row.status == "fail" for row in requirements),
        "blocked_count": sum(row.status == "blocked" for row in requirements),
        "not_run_count": sum(row.status == "not_run" for row in requirements),
    }
    pack_payload = {
        "candidate": {
            "version": candidate.version,
            "source_kind": candidate.source_kind,
            "environment": candidate.environment,
            "commit_sha": candidate.commit_sha,
            "schema_version": candidate.schema_version,
        },
        "requirements": [
            {
                "key": row.requirement_key,
                "adl_id": row.adl_id,
                "acceptance_id": row.acceptance_id,
                "test_id": row.test_id,
                "status": row.status,
                "required_evidence_level": row.required_evidence_level,
                "observed_evidence_level": row.observed_evidence_level,
                "evidence_refs": row.evidence_refs,
                "reviewer_id": row.reviewer_id,
                "executed_at": row.executed_at.isoformat() if row.executed_at else None,
            }
            for row in requirements
        ],
        "summary": summary,
        "blockers": blockers,
    }
    verdict = "no_go" if blockers else "ready_for_signature"
    decision = AcceptanceDecision(
        org_id=org_id,
        candidate_id=candidate.id,
        evaluation_key=evaluation_key,
        verdict=verdict,
        blockers=blockers,
        requirement_summary=summary,
        pack_sha256=_digest(pack_payload),
        signer_snapshot={},
        rationale="Acceptance evidence is incomplete" if blockers else "Evidence pack is ready for human signatures",
        evaluated_at=evaluated_at,
    )
    candidate.status = "evaluated"
    db.add(decision)
    await db.flush()
    return decision
