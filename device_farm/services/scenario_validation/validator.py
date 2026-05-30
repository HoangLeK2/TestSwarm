"""ScenarioValidator — orchestrates shape, semantic, and lint checks."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import Scenario
from db.models.scenario_version import ScenarioVersion
from services.scenario_validation.checks import (
    check_graph,
    check_lint_warnings,
    check_on_error_targets,
    check_retry_config,
    check_scenario_references,
    check_shape,
    check_variables,
)
from services.scenario_validation.models import ValidationResult
from services.scenario_validation.ref_cache import ScenarioRefCache
from services.scenario_validation.step_index import StepIndex

_SCENARIO_VALIDATE_DURATION: Any = None
_SCENARIO_VALIDATE_ERRORS: Any = None


def _ensure_metrics() -> None:
    global _SCENARIO_VALIDATE_DURATION, _SCENARIO_VALIDATE_ERRORS
    if _SCENARIO_VALIDATE_DURATION is not None:
        return
    from prometheus_client import Counter, Histogram

    _SCENARIO_VALIDATE_DURATION = Histogram(
        "scenario_validate_duration_ms",
        "Scenario validation duration in milliseconds",
        buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500],
    )
    _SCENARIO_VALIDATE_ERRORS = Counter(
        "scenario_validate_error_code_total",
        "Scenario validation issues by code and level",
        ["code", "level"],
    )


def _record_metrics(result: ValidationResult, duration_ms: float) -> None:
    _ensure_metrics()
    _SCENARIO_VALIDATE_DURATION.observe(duration_ms)
    for issue in result.all_issues():
        _SCENARIO_VALIDATE_ERRORS.labels(code=issue.code, level=issue.level).inc()


def build_scenario_body_from_row(scenario: Scenario) -> dict[str, Any]:
    return {
        "instructions": scenario.instructions or "",
        "steps": scenario.steps or [],
        "nodes": scenario.nodes or [],
        "edges": scenario.edges or [],
        "variables": scenario.variables or {},
    }


class ScenarioValidator:
    """Runs the full validation pipeline for a scenario body."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        scenario: Scenario,
        campaign_variables: dict[str, Any] | None = None,
        body_override: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.scenario = scenario
        self.campaign_variables = campaign_variables or {}
        self.body = body_override if body_override is not None else build_scenario_body_from_row(scenario)
        self._ref_cache: ScenarioRefCache | None = None
        self._compiled_steps: list[dict] | None = None

    async def validate(self) -> ValidationResult:
        started = time.perf_counter()
        result = ValidationResult()

        check_shape(self.body, result)
        nodes = self.body.get("nodes") or []
        edges = self.body.get("edges") or []
        if nodes:
            check_graph(nodes, edges, result)

        steps = self._resolved_steps()
        if steps:
            index = StepIndex.build(steps)
            scenario_vars = self.body.get("variables") or {}
            check_variables(index, scenario_vars, self.campaign_variables, result)
            check_on_error_targets(index, result)
            check_retry_config(index, result)

            ref_cache = await self._ref_cache_loaded()
            await check_scenario_references(
                self.scenario.id,
                steps,
                ref_cache=ref_cache,
                result=result,
            )
            check_lint_warnings(
                index,
                scenario_vars=scenario_vars,
                account_group_id=getattr(self.scenario, "account_group_id", None),
                campaign_vars=self.campaign_variables,
                result=result,
            )

        _record_metrics(result, (time.perf_counter() - started) * 1000.0)
        return result

    def _resolved_steps(self) -> list[dict]:
        if self._compiled_steps is not None:
            return self._compiled_steps
        steps = self.body.get("steps")
        if isinstance(steps, list) and steps:
            self._compiled_steps = steps
            return steps
        nodes = self.body.get("nodes")
        edges = self.body.get("edges")
        if isinstance(nodes, list) and nodes:
            from common.graph_compiler import compile_graph_to_steps

            self._compiled_steps = compile_graph_to_steps(nodes, edges or [])
            return self._compiled_steps
        self._compiled_steps = []
        return self._compiled_steps

    async def _ref_cache_loaded(self) -> ScenarioRefCache:
        if self._ref_cache is not None:
            return self._ref_cache

        result = await self.db.execute(
            select(Scenario).where(Scenario.campaign_id == self.scenario.campaign_id)
        )
        scenarios = list(result.scalars().all())
        scenario_ids = [s.id for s in scenarios]

        version_pairs: list[tuple[str, int]] = []
        if scenario_ids:
            ver_result = await self.db.execute(
                select(ScenarioVersion.scenario_id, ScenarioVersion.version).where(
                    ScenarioVersion.scenario_id.in_(scenario_ids)
                )
            )
            version_pairs = [(str(sid), int(ver)) for sid, ver in ver_result.all()]

        cache = ScenarioRefCache(scenarios, version_pairs=version_pairs)

        # Draft body on the scenario being edited overrides DB snapshot for that id.
        draft = self._draft_scenario_row()
        if draft is not None:
            cache.register(draft)

        self._ref_cache = cache
        return cache

    def _draft_scenario_row(self) -> SimpleNamespace | None:
        """Overlay row for current scenario when validating unsaved body."""
        steps = self._resolved_steps()
        has_var_patch = "variables" in self.body
        if not steps and not has_var_patch:
            return None
        variables = self.body.get("variables") if has_var_patch else (self.scenario.variables or {})
        return SimpleNamespace(
            id=self.scenario.id,
            name=self.scenario.name,
            steps=steps,
            variables=variables,
        )


async def validate_scenario_body(
    db: AsyncSession,
    scenario: Scenario,
    *,
    body: dict[str, Any] | None = None,
    campaign_variables: dict[str, Any] | None = None,
) -> ValidationResult:
    validator = ScenarioValidator(
        db,
        scenario=scenario,
        campaign_variables=campaign_variables,
        body_override=body,
    )
    return await validator.validate()


async def persist_validation_summary(
    db: AsyncSession,
    scenario_id: str,
    result: ValidationResult,
) -> None:
    from db import crud as repo

    await repo.update_scenario(
        db,
        scenario_id,
        last_validation_summary=result.to_summary_dict(),
        last_validated_at=datetime.now(timezone.utc),
    )
