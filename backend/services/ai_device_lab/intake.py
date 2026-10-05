"""Persisted AI Device Lab intake and generated-scenario lifecycle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.scenario_schema import validate_scenario
from db.models.ai_device_lab import (
    AiLabIntake,
    AppBuild,
    ScenarioApproval,
    ScenarioGenerationOperation,
    ServiceCampaign,
)
from db.models.campaign import Campaign, Scenario
from db.models.scenario_version import ScenarioVersion
from services.ai_device_lab.funnel import record_server_funnel_event
from services.operation_policy import OperationPolicy, evaluate_scenario_operations


class IntakeInvariantError(ValueError):
    pass


class ScenarioGenerationRejected(ValueError):
    def __init__(self, reason_code: str, path: str | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.path = path


@dataclass(frozen=True, slots=True)
class CreateIntake:
    org_id: str
    owner_id: str
    runtime_campaign_id: str
    requested_build_id: str
    package_name: str
    closed_track_link: str
    test_goal: str
    test_environment: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CompleteGeneration:
    org_id: str
    operation_id: str
    scenario_name: str
    scenario: dict[str, Any]
    policy: OperationPolicy
    provider_request_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ApproveScenario:
    org_id: str
    operation_id: str
    scenario_version_id: str
    expected_content_hash: str
    approved_by: str
    policy: OperationPolicy


def scenario_version_content_hash(version: ScenarioVersion) -> str:
    """Return a stable digest of every execution-relevant snapshot field."""

    payload = {
        "steps": version.steps or [],
        "nodes": version.nodes or [],
        "edges": version.edges or [],
        "variables": version.variables or {},
        "requirements": version.requirements or {},
        "instructions": version.instructions or "",
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _walk_scenario_steps(steps: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stack: list[Any] = list(reversed(steps))
    while stack:
        step = stack.pop()
        if not isinstance(step, dict):
            continue
        result.append(step)
        for key in ("steps", "then", "else", "body", "options"):
            nested = step.get(key)
            if isinstance(nested, list):
                stack.extend(reversed(nested))
    return result


def _version_scenario(version: ScenarioVersion) -> dict[str, Any]:
    return {
        "steps": version.steps or [],
        "nodes": version.nodes or [],
        "edges": version.edges or [],
        "variables": version.variables or {},
        "requirements": version.requirements or {},
    }


async def approve_scenario(
    db: AsyncSession,
    command: ApproveScenario,
) -> ScenarioApproval:
    operation = (
        await db.execute(
            select(ScenarioGenerationOperation).where(
                ScenarioGenerationOperation.org_id == command.org_id,
                ScenarioGenerationOperation.operation_id == command.operation_id,
            )
        )
    ).scalar_one_or_none()
    if (
        operation is None
        or operation.status != "succeeded"
        or operation.scenario_version_id != command.scenario_version_id
    ):
        raise ScenarioGenerationRejected("GENERATION_NOT_APPROVABLE")

    intake = (
        await db.execute(
            select(AiLabIntake).where(
                AiLabIntake.id == operation.intake_id,
                AiLabIntake.org_id == command.org_id,
            )
        )
    ).scalar_one()
    if (
        operation.input_version != intake.input_version
        or operation.input_hash != intake.input_hash
    ):
        raise ScenarioGenerationRejected("STALE_GENERATION_INPUT")
    version = await db.get(ScenarioVersion, command.scenario_version_id)
    if version is None or version.id != operation.scenario_version_id:
        raise ScenarioGenerationRejected("SCENARIO_VERSION_NOT_FOUND")
    content_hash = scenario_version_content_hash(version)
    if content_hash != command.expected_content_hash:
        raise ScenarioGenerationRejected("SCENARIO_CONTENT_CHANGED")

    existing = (
        await db.execute(
            select(ScenarioApproval).where(
                ScenarioApproval.org_id == command.org_id,
                ScenarioApproval.scenario_version_id == version.id,
                ScenarioApproval.content_hash == content_hash,
                ScenarioApproval.policy_version == command.policy.version,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.approved_by != command.approved_by:
            raise ScenarioGenerationRejected("ALREADY_APPROVED_BY_ANOTHER_ACTOR")
        return existing

    violations = evaluate_scenario_operations(
        command.policy,
        _version_scenario(version),
        observed_package=intake.package_name,
        approval_policy_version=command.policy.version,
    )
    if violations:
        violation = violations[0]
        raise ScenarioGenerationRejected(violation.reason_code, violation.path)

    all_steps = _walk_scenario_steps(list(version.steps or []))
    assertions = [
        step
        for step in all_steps
        if str(step.get("type") or "").startswith(("assert_", "verify_screen"))
    ]
    if not assertions:
        raise ScenarioGenerationRejected("ASSERTION_REQUIRED")
    allowed_operations = sorted(
        {
            str(step["semantic_action"])
            for step in all_steps
            if step.get("semantic_action")
        }
    )
    approval = ScenarioApproval(
        org_id=command.org_id,
        intake_id=intake.id,
        generation_operation_id=operation.id,
        scenario_version_id=version.id,
        content_hash=content_hash,
        policy_version=command.policy.version,
        assertions=assertions,
        allowed_operations=allowed_operations,
        package_name=intake.package_name,
        approved_by=command.approved_by,
    )
    db.add(approval)
    await db.flush()
    service_campaign_id = await db.scalar(
        select(ServiceCampaign.id).where(
            ServiceCampaign.org_id == command.org_id,
            ServiceCampaign.runtime_campaign_id == intake.runtime_campaign_id,
        )
    )
    if service_campaign_id is not None:
        await record_server_funnel_event(
            db,
            org_id=command.org_id,
            service_campaign_id=service_campaign_id,
            event_name="scenario_approved",
            source_ref=approval.id,
            occurred_at=approval.approved_at,
        )
    return approval


async def authorize_approved_scenario(
    db: AsyncSession,
    *,
    org_id: str,
    approval_id: str,
    scenario_version_id: str,
    active_policy: OperationPolicy,
) -> ScenarioVersion:
    approval = (
        await db.execute(
            select(ScenarioApproval).where(
                ScenarioApproval.id == approval_id,
                ScenarioApproval.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if approval is None:
        raise ScenarioGenerationRejected("APPROVAL_NOT_FOUND")
    if approval.scenario_version_id != scenario_version_id:
        raise ScenarioGenerationRejected("APPROVAL_VERSION_MISMATCH")
    if approval.policy_version != active_policy.version:
        raise ScenarioGenerationRejected("STALE_POLICY_APPROVAL")

    version = await db.get(ScenarioVersion, scenario_version_id)
    if version is None:
        raise ScenarioGenerationRejected("SCENARIO_VERSION_NOT_FOUND")
    if scenario_version_content_hash(version) != approval.content_hash:
        raise ScenarioGenerationRejected("APPROVED_CONTENT_MISMATCH")
    violations = evaluate_scenario_operations(
        active_policy,
        _version_scenario(version),
        observed_package=approval.package_name,
        approval_policy_version=approval.policy_version,
    )
    if violations:
        violation = violations[0]
        raise ScenarioGenerationRejected(violation.reason_code, violation.path)
    return version


def _intake_hash(command: CreateIntake) -> str:
    payload = {
        "package_name": command.package_name,
        "closed_track_link": command.closed_track_link,
        "test_goal": command.test_goal,
        "test_environment": command.test_environment,
        "requested_build_id": command.requested_build_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def create_intake(db: AsyncSession, command: CreateIntake) -> AiLabIntake:
    if not command.test_goal.strip():
        raise IntakeInvariantError("test_goal is required")
    runtime_campaign_id = await db.scalar(
        select(Campaign.__table__.c.id).where(
            Campaign.__table__.c.id == command.runtime_campaign_id,
            Campaign.__table__.c.org_id == command.org_id,
        )
    )
    build_package = await db.scalar(
        select(AppBuild.__table__.c.package_name).where(
            AppBuild.__table__.c.id == command.requested_build_id,
            AppBuild.__table__.c.org_id == command.org_id,
        )
    )
    if runtime_campaign_id is None or build_package != command.package_name:
        raise IntakeInvariantError("campaign/build is outside intake scope")
    intake = AiLabIntake(
        org_id=command.org_id,
        owner_id=command.owner_id,
        runtime_campaign_id=command.runtime_campaign_id,
        requested_build_id=command.requested_build_id,
        package_name=command.package_name,
        closed_track_link=command.closed_track_link,
        test_goal=command.test_goal.strip(),
        test_environment=command.test_environment,
        input_version=1,
        input_hash=_intake_hash(command),
        status="draft",
    )
    db.add(intake)
    await db.flush()
    return intake


async def start_generation(
    db: AsyncSession,
    *,
    intake_id: str,
    org_id: str,
    operation_id: str,
) -> ScenarioGenerationOperation:
    existing = (
        await db.execute(
            select(ScenarioGenerationOperation).where(
                ScenarioGenerationOperation.org_id == org_id,
                ScenarioGenerationOperation.operation_id == operation_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.intake_id != intake_id:
            raise IntakeInvariantError("generation operation id was reused for another intake")
        return existing
    intake = (
        await db.execute(
            select(AiLabIntake).where(
                AiLabIntake.id == intake_id,
                AiLabIntake.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if intake is None:
        raise IntakeInvariantError("intake not found in organization")
    operation = ScenarioGenerationOperation(
        org_id=org_id,
        intake_id=intake.id,
        operation_id=operation_id,
        input_version=intake.input_version,
        input_hash=intake.input_hash,
        status="running",
    )
    db.add(operation)
    await db.flush()
    return operation


async def complete_generation(
    db: AsyncSession,
    command: CompleteGeneration,
) -> ScenarioVersion:
    operation = (
        await db.execute(
            select(ScenarioGenerationOperation).where(
                ScenarioGenerationOperation.org_id == command.org_id,
                ScenarioGenerationOperation.operation_id == command.operation_id,
            )
        )
    ).scalar_one_or_none()
    if operation is None:
        raise IntakeInvariantError("generation operation not found")
    if operation.status == "succeeded" and operation.scenario_version_id:
        completed_version = await db.get(
            ScenarioVersion,
            operation.scenario_version_id,
        )
        if completed_version is None:
            raise ScenarioGenerationRejected("COMPLETED_VERSION_MISSING")
        supplied_payload = {
            "steps": command.scenario.get("steps") or [],
            "nodes": command.scenario.get("nodes") or [],
            "edges": command.scenario.get("edges") or [],
            "variables": command.scenario.get("variables") or {},
            "requirements": command.scenario.get("requirements") or {},
            "instructions": completed_version.instructions or "",
        }
        canonical = json.dumps(
            supplied_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        supplied_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if supplied_hash == scenario_version_content_hash(completed_version):
            return completed_version
        raise ScenarioGenerationRejected("OPERATION_ALREADY_COMPLETED")
    if operation.status != "running":
        raise ScenarioGenerationRejected("GENERATION_NOT_RUNNING")
    intake = (
        await db.execute(
            select(AiLabIntake).where(
                AiLabIntake.id == operation.intake_id,
                AiLabIntake.org_id == command.org_id,
            )
        )
    ).scalar_one()
    if (
        operation.input_version != intake.input_version
        or operation.input_hash != intake.input_hash
    ):
        operation.status = "failed"
        operation.error_code = "STALE_GENERATION_INPUT"
        operation.finished_at = datetime.now(timezone.utc)
        await db.flush()
        raise ScenarioGenerationRejected("STALE_GENERATION_INPUT")

    violations = evaluate_scenario_operations(
        command.policy,
        command.scenario,
        observed_package=intake.package_name,
        approval_policy_version=command.policy.version,
    )
    if violations:
        violation = violations[0]
        operation.status = "failed"
        operation.error_code = violation.reason_code
        operation.finished_at = datetime.now(timezone.utc)
        await db.flush()
        raise ScenarioGenerationRejected(violation.reason_code, violation.path)

    validation_errors = validate_scenario(command.scenario)
    if validation_errors:
        operation.status = "failed"
        operation.error_code = "SCENARIO_SCHEMA_INVALID"
        operation.finished_at = datetime.now(timezone.utc)
        await db.flush()
        raise ScenarioGenerationRejected("SCENARIO_SCHEMA_INVALID")
    if not any(
        str(step.get("type") or "").startswith(("assert_", "verify_screen"))
        for step in _walk_scenario_steps(command.scenario.get("steps", []))
    ):
        operation.status = "failed"
        operation.error_code = "ASSERTION_REQUIRED"
        operation.finished_at = datetime.now(timezone.utc)
        await db.flush()
        raise ScenarioGenerationRejected("ASSERTION_REQUIRED")

    scenario = Scenario(
        campaign_id=intake.runtime_campaign_id,
        name=command.scenario_name,
        instructions=intake.test_goal,
        steps=command.scenario["steps"],
        variables=command.scenario.get("variables") or {},
        requirements=command.scenario.get("requirements") or {},
    )
    db.add(scenario)
    await db.flush()
    version = ScenarioVersion(
        scenario_id=scenario.id,
        version=1,
        steps=list(scenario.steps),
        nodes=list(scenario.nodes),
        edges=list(scenario.edges),
        variables=dict(scenario.variables),
        requirements=dict(scenario.requirements),
        instructions=scenario.instructions,
    )
    db.add(version)
    await db.flush()
    operation.status = "succeeded"
    operation.provider_request_ref = command.provider_request_ref
    operation.scenario_id = scenario.id
    operation.scenario_version_id = version.id
    operation.finished_at = datetime.now(timezone.utc)
    intake.status = "scenario_generated"
    await db.flush()
    return version
