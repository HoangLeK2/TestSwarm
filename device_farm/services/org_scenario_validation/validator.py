"""Org-scenario validation pipeline orchestrator (DF-T-04-004)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import ScenarioKind
from db.models.org_scenario import OrgScenario
from services.org_scenario_validation.checks import (
    build_org_ref_cache,
    check_content_interaction_verify,
    check_lint_warnings,
    check_on_error_targets,
    check_org_graph,
    check_org_scenario_references,
    check_retry_config,
    check_step_fields,
    check_variables,
)
from services.org_scenario_validation.step_index import OrgStepIndex
from services.scenario_dsl.body_validator import get_org_nesting_depth_limit, validate_org_scenario_body
from services.scenario_validation import codes as C
from services.scenario_validation.models import ValidationIssue, ValidationResult

_SCENARIO_VALIDATE_DURATION: Any = None
_SCENARIO_VALIDATE_ERRORS: Any = None


def _ensure_metrics() -> None:
    global _SCENARIO_VALIDATE_DURATION, _SCENARIO_VALIDATE_ERRORS
    if _SCENARIO_VALIDATE_DURATION is not None:
        return
    from prometheus_client import Counter, Histogram

    _SCENARIO_VALIDATE_DURATION = Histogram(
        "org_scenario_validate_duration_ms",
        "Org scenario validation duration in milliseconds",
        buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500],
    )
    _SCENARIO_VALIDATE_ERRORS = Counter(
        "org_scenario_validate_error_code_total",
        "Org scenario validation issues by code and level",
        ["code", "level"],
    )


def _record_metrics(result: ValidationResult, duration_ms: float) -> None:
    _ensure_metrics()
    _SCENARIO_VALIDATE_DURATION.observe(duration_ms)
    seen: set[tuple[str, str]] = set()
    for issue in result.all_issues():
        key = (issue.code, issue.level)
        if key in seen:
            continue
        seen.add(key)
        _SCENARIO_VALIDATE_ERRORS.labels(code=issue.code, level=issue.level).inc()


def _merge_shape_errors(shape_result, result: ValidationResult) -> bool:
    """Return True if shape layer produced blocking errors."""
    for issue in shape_result.errors:
        result.add(
            ValidationIssue(
                level="error",
                code=issue.code,
                message=issue.message,
                location=issue.location,
            )
        )
    return bool(shape_result.errors)


class OrgScenarioValidator:
    """Runs shape + semantic + lint validation for org-scenario bodies."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        scenario: OrgScenario,
        body: dict[str, Any],
        campaign_variables: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.scenario = scenario
        self.body = body
        self.campaign_variables = campaign_variables or {}
        self._normalized_body: dict[str, Any] | None = None

    async def validate(self) -> ValidationResult:
        started = time.perf_counter()
        result = ValidationResult()
        depth_limit = get_org_nesting_depth_limit(self.scenario.org_id)

        shape_result = await validate_org_scenario_body(
            self.db,
            org_id=self.scenario.org_id,
            scenario_id=self.scenario.id,
            kind=self.scenario.kind,
            body=self.body,
            depth_limit=depth_limit,
        )
        has_shape_errors = _merge_shape_errors(shape_result, result)
        body = shape_result.normalized_body or self.body
        self._normalized_body = shape_result.normalized_body if not has_shape_errors else None

        if has_shape_errors:
            _record_metrics(result, (time.perf_counter() - started) * 1000.0)
            return result

        kind = self.scenario.kind or ScenarioKind.SEQUENCE.value
        if kind == ScenarioKind.GRAPH.value:
            nodes = body.get("nodes") or []
            edges = body.get("edges") or []
            if isinstance(nodes, list) and isinstance(edges, list):
                check_org_graph(nodes, edges, result)
                index = OrgStepIndex.build(nodes, path_prefix="nodes")
            else:
                index = OrgStepIndex.empty()
        else:
            steps = body.get("steps") or []
            index = OrgStepIndex.build(steps if isinstance(steps, list) else [])

        if index.entries:
            scenario_vars = body.get("variables") or {}
            check_variables(index, scenario_vars, self.campaign_variables, result)
            check_on_error_targets(index, result)
            check_retry_config(index, result)
            check_step_fields(index, result)
            check_content_interaction_verify(index, result)

            ref_cache = await build_org_ref_cache(
                self.db,
                org_id=self.scenario.org_id,
                root_scenario_id=self.scenario.id,
                root_kind=kind,
                root_body=body,
                root_status=self.scenario.status,
                root_version=int(self.scenario.scenario_version or 1),
                depth_limit=depth_limit,
            )
            check_org_scenario_references(
                self.scenario.id,
                index,
                ref_cache=ref_cache,
                result=result,
            )
            check_lint_warnings(
                index,
                scenario_vars=scenario_vars,
                campaign_vars=self.campaign_variables,
                result=result,
            )

        _record_metrics(result, (time.perf_counter() - started) * 1000.0)
        return result


async def validate_org_scenario(
    db: AsyncSession,
    scenario: OrgScenario,
    *,
    body: dict[str, Any] | None = None,
    campaign_variables: dict[str, Any] | None = None,
) -> tuple[ValidationResult, dict[str, Any] | None]:
    """Validate org scenario; returns (result, normalized_body_if_shape_ok)."""
    effective_body = body if body is not None else (scenario.body_json or {})
    validator = OrgScenarioValidator(
        db,
        scenario=scenario,
        body=effective_body,
        campaign_variables=campaign_variables,
    )
    result = await validator.validate()
    return result, validator._normalized_body


async def persist_org_validation_summary(
    db: AsyncSession,
    row: OrgScenario,
    result: ValidationResult,
) -> OrgScenario:
    from db.crud import org_scenario as repo

    now = datetime.now(timezone.utc)
    return await repo.update_org_scenario(
        db,
        row,
        last_validation_summary=result.to_summary_dict(),
        last_validated_at=now,
    )
