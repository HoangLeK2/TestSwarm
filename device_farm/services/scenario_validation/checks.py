"""Individual validation checks for scenario bodies."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from common.variable_resolver import _BUILTIN_NAMES, _VAR_PATTERN, normalize_variable_map
from services.scenario_validation import codes as C
from services.scenario_validation.models import ValidationIssue, ValidationResult
from services.scenario_validation.ref_cache import ScenarioRefCache, steps_from_row
from services.scenario_validation.step_index import StepIndex

_MAX_NESTING_DEPTH = 10
_TERMINAL_NODE_TYPES = frozenset({"success", "fail", "end", "terminal"})
_ERROR_POLICIES = frozenset({"pause", "continue", "stop"})

# Skip ${var} scan inside heavy / non-interpolated fields (screenshots, anchors).
_SKIP_VAR_SCAN_KEYS = frozenset({
    "screenshot",
    "element_image",
    "image",
    "screenshot_anchor",
    "ui_xml",
    "hierarchy_xml",
})


def check_shape(body: dict[str, Any], result: ValidationResult) -> None:
    """Layer 1 — Pydantic shape validation (DF-T-04-002)."""
    if not body.get("steps") and not body.get("nodes"):
        return
    payload: dict[str, Any] = {}
    if body.get("steps"):
        payload["steps"] = body["steps"]
    if body.get("variables") is not None:
        payload["variables"] = body.get("variables") or {}
    for key in ("instructions", "implicit_wait", "visual_anchor", "capture_steps"):
        if key in body:
            payload[key] = body[key]

    if not payload.get("steps"):
        return

    from api.schemas.scenario import ScenarioModel

    shape_errors = ScenarioModel.validate_dict(payload)
    for msg in shape_errors[:50]:
        result.add(
            ValidationIssue(
                level="error",
                code=C.SHAPE_VALIDATION_FAILED,
                message=msg,
                location="scenario",
            )
        )


def check_graph(nodes: list[dict], edges: list[dict], result: ValidationResult) -> None:
    """Graph reachability and dead-end detection."""
    if not nodes:
        return

    node_by_id = {n["id"]: n for n in nodes if n.get("id")}
    if not node_by_id:
        return

    adj: dict[str, list[str]] = defaultdict(list)
    for edge in edges or []:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in node_by_id and tgt in node_by_id:
            adj[src].append(tgt)

    root_nodes = [n for n in nodes if not (n.get("scope") or {}).get("parentId")]
    root_nodes.sort(key=lambda n: n.get("order", ""))
    if not root_nodes:
        return

    visited: set[str] = set()
    queue: deque[str] = deque([root_nodes[0]["id"]])
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        for tgt in adj.get(nid, []):
            if tgt not in visited:
                queue.append(tgt)

    for node in nodes:
        nid = node.get("id")
        if not nid:
            continue
        title = node.get("title") or nid
        if nid not in visited:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.GRAPH_UNREACHABLE_NODE,
                    message=f"Node {title!r} is not reachable from the scenario start",
                    location=f"node.{nid}",
                )
            )
            continue
        if not adj.get(nid) and str(node.get("type") or "") not in _TERMINAL_NODE_TYPES:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.GRAPH_DEAD_END_NODE,
                    message=f"Node {title!r} has no outgoing edges and is not a terminal node",
                    location=f"node.{nid}",
                )
            )


def _scan_var_refs(value: Any, path: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        if "${" in value:
            for m in _VAR_PATTERN.finditer(value):
                found.append((m.group(1), path))
    elif isinstance(value, dict):
        for k, v in value.items():
            if k in _SKIP_VAR_SCAN_KEYS:
                continue
            found.extend(_scan_var_refs(v, f"{path}.{k}"))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.extend(_scan_var_refs(item, f"{path}[{i}]"))
    return found


def check_variables(
    index: StepIndex,
    scenario_vars: dict[str, Any],
    campaign_vars: dict[str, Any],
    result: ValidationResult,
) -> None:
    declared: set[str] = set(normalize_variable_map(scenario_vars).keys())
    declared |= set(normalize_variable_map(campaign_vars).keys())
    declared |= set(_BUILTIN_NAMES)

    for step, loc, _sid in index.entries:
        for var_name, ref_path in _scan_var_refs(step, loc):
            if var_name not in declared:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.UNDECLARED_VARIABLE,
                        message=f"${{{var_name}}} chưa được declared ở tầng nào",
                        location=ref_path,
                    )
                )
        if step.get("type") == "set_variable":
            name = step.get("name")
            if isinstance(name, str) and name:
                declared.add(name)


def check_on_error_targets(index: StepIndex, result: ValidationResult) -> None:
    for step, loc, sid in index.entries:
        on_error = step.get("on_error")
        if on_error is None or on_error == "":
            continue
        policy = str(on_error)
        if policy in _ERROR_POLICIES:
            continue
        if policy not in index.step_ids:
            loc_on_error = f"step.{sid}.on_error" if sid else f"{loc}.on_error"
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.INVALID_ON_ERROR_TARGET,
                    message=f"on_error target {policy!r} does not exist in this scenario",
                    location=loc_on_error,
                )
            )


def check_retry_config(index: StepIndex, result: ValidationResult) -> None:
    for step, loc, _sid in index.entries:
        retry = step.get("retry")
        if not isinstance(retry, dict):
            continue
        attempts = retry.get("attempts", retry.get("max_attempts", 1))
        try:
            max_attempts = int(attempts)
        except (TypeError, ValueError):
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.INVALID_RETRY_CONFIG,
                    message="retry.attempts must be an integer",
                    location=f"{loc}.retry.attempts",
                )
            )
            continue
        if max_attempts < 1 or max_attempts > 10:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.INVALID_RETRY_CONFIG,
                    message="retry.attempts must be between 1 and 10",
                    location=f"{loc}.retry.attempts",
                )
            )
        for key in ("backoff_ms", "jitter_ms", "backoff_cap_ms"):
            val = retry.get(key)
            if val is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.INVALID_RETRY_CONFIG,
                        message=f"retry.{key} must be a positive number",
                        location=f"{loc}.retry.{key}",
                    )
                )
                continue
            if num < 0:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.INVALID_RETRY_CONFIG,
                        message=f"retry.{key} must be positive",
                        location=f"{loc}.retry.{key}",
                    )
                )


def check_lint_warnings(
    index: StepIndex,
    *,
    scenario_vars: dict[str, Any],
    account_group_id: str | None,
    campaign_vars: dict[str, Any],
    result: ValidationResult,
) -> None:
    validation_meta = (
        scenario_vars.get("_validation")
        if isinstance(scenario_vars.get("_validation"), dict)
        else {}
    )
    if validation_meta.get("skip_no_verification"):
        pass
    elif index.has_interaction and not index.has_verification:
        result.add(
            ValidationIssue(
                level="warning",
                code=C.NO_VERIFICATION_STEP,
                message="scenario UI-gated khuyến nghị có ít nhất 1 verification (verify_screen)",
                location="scenario",
                hint="Add a verify_screen step or set variables._validation.skip_no_verification=true",
            )
        )

    camp = normalize_variable_map(campaign_vars)
    has_account_binding = bool(account_group_id) or bool(camp.get("__ACCOUNT_ID__"))
    if index.has_social and not has_account_binding:
        result.add(
            ValidationIssue(
                level="warning",
                code=C.IMPLICIT_ACCOUNT_FALLBACK,
                message="Social platform steps may use implicit primary-account fallback; bind account_group_id or set campaign __ACCOUNT_* vars",
                location="scenario",
            )
        )


async def check_scenario_references(
    root_scenario_id: str,
    root_steps: list[dict],
    *,
    ref_cache: ScenarioRefCache,
    result: ValidationResult,
) -> None:
    """Resolve run_scenario refs using preloaded campaign cache (no per-ref DB queries)."""

    async def walk(scenario_id: str, steps: list[dict], stack: list[str], depth: int) -> None:
        if depth > _MAX_NESTING_DEPTH:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.SCENARIO_DEPTH_EXCEEDED,
                    message=f"Nested scenario depth exceeds limit ({_MAX_NESTING_DEPTH})",
                    location="scenario",
                )
            )
            return

        index = ref_cache.index_for(scenario_id, steps)
        for step, loc, _sid in index.run_scenario_refs:
            scenario_id_ref = str(step.get("scenario_id") or "").strip()
            scenario_name = str(step.get("scenario_name") or "").strip()
            ref = scenario_id_ref or scenario_name
            if not ref:
                continue

            if ref in stack:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.CIRCULAR_SCENARIO_REFERENCE,
                        message=f"Circular scenario reference: {' -> '.join([*stack, ref])}",
                        location=loc,
                    )
                )
                continue

            row = ref_cache.get_by_id(scenario_id_ref) if scenario_id_ref else None
            if row is None and scenario_name:
                row = ref_cache.get_by_name(scenario_name)

            if row is None:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.SCENARIO_REF_NOT_FOUND,
                        message=f"Referenced scenario not found: {ref!r}",
                        location=loc,
                    )
                )
                continue

            if _is_archived(row):
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.SCENARIO_REF_ARCHIVED,
                        message=f"Referenced scenario is archived: {ref!r}",
                        location=loc,
                    )
                )

            sub_id = row.id
            version_raw = step.get("scenario_version")
            if version_raw is not None and scenario_id_ref:
                try:
                    version_num = int(version_raw)
                except (TypeError, ValueError):
                    result.add(
                        ValidationIssue(
                            level="error",
                            code=C.SCENARIO_VERSION_NOT_FOUND,
                            message=f"scenario_version must be an integer, got {version_raw!r}",
                            location=f"{loc}.scenario_version",
                        )
                    )
                    continue
                if not ref_cache.has_version(scenario_id_ref, version_num):
                    result.add(
                        ValidationIssue(
                            level="error",
                            code=C.SCENARIO_VERSION_NOT_FOUND,
                            message=f"scenario_version {version_num} does not exist for scenario {scenario_id_ref!r}",
                            location=f"{loc}.scenario_version",
                        )
                    )
                    continue

            sub_steps = steps_from_row(row)
            await walk(sub_id, sub_steps, [*stack, sub_id], depth + 1)

    await walk(root_scenario_id, root_steps, [root_scenario_id], 0)


def _is_archived(row: Any) -> bool:
    variables = getattr(row, "variables", None)
    if variables is None and isinstance(row, dict):
        variables = row.get("variables")
    if not isinstance(variables, dict):
        return False
    meta = variables.get("_meta")
    if isinstance(meta, dict) and meta.get("archived"):
        return True
    return bool(variables.get("_archived"))
