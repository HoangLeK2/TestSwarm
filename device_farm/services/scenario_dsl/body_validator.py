"""Shape validation for org scenario DSL bodies (DF-T-04-002)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import ScenarioKind
from services.scenario_dsl import codes as C
from services.scenario_dsl.models import BodyValidationIssue, BodyValidationResult
from services.scenario_dsl.step_contract import normalize_body_steps
from services.scenario_dsl.step_family import DEFAULT_NESTING_DEPTH_LIMIT
from services.scenario_dsl.step_registry import StepRegistry

_SCENARIO_BODY_VALIDATE_FAIL: Any = None
_SUPPORTED_FAMILIES = StepRegistry.supported_families()


def _ensure_metrics() -> None:
    global _SCENARIO_BODY_VALIDATE_FAIL
    if _SCENARIO_BODY_VALIDATE_FAIL is not None:
        return
    from prometheus_client import Counter

    _SCENARIO_BODY_VALIDATE_FAIL = Counter(
        "scenario_body_validate_fail_total",
        "Org scenario body validation failures by error code",
        ["code"],
    )


def record_validation_failures(codes: list[str]) -> None:
    if not codes:
        return
    _ensure_metrics()
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        _SCENARIO_BODY_VALIDATE_FAIL.labels(code=code).inc()


def get_org_nesting_depth_limit(_org_id: str) -> int:
    """Org-configurable depth limit (default 5). Hook for org settings in future."""
    return DEFAULT_NESTING_DEPTH_LIMIT


def _collect_step_like_objects(body: dict[str, Any], kind: str) -> list[tuple[dict[str, Any], str]]:
    items: list[tuple[dict[str, Any], str]] = []
    if kind == ScenarioKind.SEQUENCE.value:
        steps = body.get("steps") or []
        if isinstance(steps, list):
            for idx, step in enumerate(steps):
                if isinstance(step, dict):
                    items.append((step, f"steps[{idx}]"))
    elif kind == ScenarioKind.GRAPH.value:
        nodes = body.get("nodes") or []
        if isinstance(nodes, list):
            for idx, node in enumerate(nodes):
                if isinstance(node, dict):
                    items.append((node, f"nodes[{idx}]"))
    return items


def _check_required_step_fields(
    step_items: list[tuple[dict[str, Any], str]],
    result: BodyValidationResult,
) -> None:
    for step, loc in step_items:
        sid = step.get("id")
        stype = step.get("type")
        if not sid or not str(sid).strip():
            result.add(
                BodyValidationIssue(
                    code=C.INVALID_STEP_SHAPE,
                    message="step id is required",
                    location=loc,
                )
            )
        if not stype or not str(stype).strip():
            result.add(
                BodyValidationIssue(
                    code=C.INVALID_STEP_SHAPE,
                    message="step type is required",
                    location=loc,
                )
            )


def _check_duplicate_step_ids(
    step_items: list[tuple[dict[str, Any], str]],
    result: BodyValidationResult,
) -> None:
    ids = [str(s[0].get("id")) for s in step_items if s[0].get("id")]
    counts = Counter(ids)
    for sid, count in counts.items():
        if count > 1:
            result.add(
                BodyValidationIssue(
                    code=C.DUPLICATE_STEP_ID,
                    message=f"Duplicate step id {sid!r}",
                    location="scenario",
                    details={"step_id": sid, "count": count},
                )
            )


def _check_step_types(step_items: list[tuple[dict[str, Any], str]], result: BodyValidationResult) -> None:
    unknown_reported = False
    for step, loc in step_items:
        stype = str(step.get("type") or "").strip()
        sid = str(step.get("id") or loc)
        if not stype:
            continue
        if not StepRegistry.is_known_type(stype):
            details: dict[str, Any] = {"step_id": sid, "step_type": stype}
            if not unknown_reported:
                details["supported_families"] = _SUPPORTED_FAMILIES
                unknown_reported = True
            result.add(
                BodyValidationIssue(
                    code=C.UNKNOWN_STEP_TYPE,
                    message=f"Unknown step type {stype!r}",
                    location=loc,
                    details=details,
                )
            )


def _check_graph_edges(body: dict[str, Any], result: BodyValidationResult) -> None:
    nodes = body.get("nodes") or []
    edges = body.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return
    node_ids = {str(n.get("id")) for n in nodes if isinstance(n, dict) and n.get("id")}
    for idx, edge in enumerate(edges):
        if not isinstance(edge, dict):
            result.add(
                BodyValidationIssue(
                    code=C.INVALID_GRAPH_EDGE,
                    message="edge must be an object",
                    location=f"edges[{idx}]",
                )
            )
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        if src not in node_ids or tgt not in node_ids:
            result.add(
                BodyValidationIssue(
                    code=C.INVALID_GRAPH_EDGE,
                    message=f"edge references unknown node(s): {src!r} -> {tgt!r}",
                    location=f"edges[{idx}]",
                    details={"source": src, "target": tgt},
                )
            )


class ScenarioBodyValidator:
    """Shape-only validator for org scenario bodies."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        scenario_id: str,
        kind: str,
        body: dict[str, Any],
        depth_limit: int | None = None,
    ) -> None:
        self.db = db
        self.org_id = org_id
        self.scenario_id = scenario_id
        self.kind = kind
        self.body = body
        self.depth_limit = depth_limit or get_org_nesting_depth_limit(org_id)

    async def validate(self) -> BodyValidationResult:
        result = BodyValidationResult()
        body = dict(self.body or {})

        if self.kind == ScenarioKind.SEQUENCE.value:
            if "steps" not in body or not isinstance(body.get("steps"), list):
                result.add(
                    BodyValidationIssue(
                        code=C.KIND_BODY_MISMATCH,
                        message="sequence kind requires a steps array",
                        location="body.steps",
                    )
                )
        elif self.kind == ScenarioKind.GRAPH.value:
            if not isinstance(body.get("nodes"), list):
                result.add(
                    BodyValidationIssue(
                        code=C.KIND_BODY_MISMATCH,
                        message="graph kind requires a nodes array",
                        location="body.nodes",
                    )
                )
            if not isinstance(body.get("edges"), list):
                result.add(
                    BodyValidationIssue(
                        code=C.KIND_BODY_MISMATCH,
                        message="graph kind requires an edges array",
                        location="body.edges",
                    )
                )
        else:
            result.add(
                BodyValidationIssue(
                    code=C.KIND_BODY_MISMATCH,
                    message=f"unsupported kind {self.kind!r}",
                    location="kind",
                )
            )
            record_validation_failures([issue.code for issue in result.errors])
            return result

        step_items = _collect_step_like_objects(body, self.kind)
        _check_required_step_fields(step_items, result)
        _check_duplicate_step_ids(step_items, result)
        _check_step_types(step_items, result)
        if self.kind == ScenarioKind.GRAPH.value:
            _check_graph_edges(body, result)

        if result.errors:
            record_validation_failures([issue.code for issue in result.errors])
            return result

        normalized = dict(body)
        if self.kind == ScenarioKind.SEQUENCE.value:
            normalized["steps"] = normalize_body_steps(body.get("steps") or [])
        else:
            normalized["nodes"] = normalize_body_steps(body.get("nodes") or [])
        if "variables" in body and isinstance(body["variables"], dict):
            normalized["variables"] = dict(body["variables"])
        result.normalized_body = normalized
        return result


async def validate_org_scenario_body(
    db: AsyncSession,
    *,
    org_id: str,
    scenario_id: str,
    kind: str,
    body: dict[str, Any],
    depth_limit: int | None = None,
) -> BodyValidationResult:
    validator = ScenarioBodyValidator(
        db,
        org_id=org_id,
        scenario_id=scenario_id,
        kind=kind,
        body=body,
        depth_limit=depth_limit,
    )
    return await validator.validate()
