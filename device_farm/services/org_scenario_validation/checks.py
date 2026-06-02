"""Semantic + lint checks for org-scenario validation (DF-T-04-004)."""

from __future__ import annotations

from typing import Any

from common.variable_resolver import _BUILTIN_NAMES, _VAR_PATTERN, normalize_variable_map
from db.models.enums import OrgScenarioStatus
from services.org_scenario_validation.step_index import OrgStepIndex
from services.scenario_dsl.ref_cache import extract_run_scenario_id, steps_from_body
from services.scenario_dsl.step_family import COMPOSITION_RUN_SCENARIO
from services.scenario_validation import codes as C
from services.scenario_validation.graph_reachability import (
    build_graph_indexes,
    is_graph_dead_end,
    last_root_node_id,
    org_start_node_id,
    reachable_from,
)
from services.scenario_validation.models import ValidationIssue, ValidationResult

_ERROR_POLICIES = frozenset({"pause", "continue", "stop", "ignore", "on_error"})
_SKIP_VAR_SCAN_KEYS = frozenset({
    "screenshot",
    "element_image",
    "image",
    "screenshot_anchor",
    "ui_xml",
    "hierarchy_xml",
    "steps",
    "then",
    "else",
    "else_steps",
    "branches",
})


def _step_config(step: dict[str, Any]) -> dict[str, Any]:
    config = step.get("config")
    return config if isinstance(config, dict) else {}


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


def check_org_graph(nodes: list[dict], edges: list[dict], result: ValidationResult) -> None:
    """Graph reachability and dead-end detection for org-scenario graph bodies."""
    if not nodes:
        return

    node_by_id, reach_adj, explicit_adj, scoped_children = build_graph_indexes(nodes, edges)
    if not node_by_id:
        return

    start_id = org_start_node_id(node_by_id, explicit_adj)
    if not start_id:
        return

    visited = reachable_from(start_id, reach_adj)
    terminal_root_id = last_root_node_id(nodes)

    for nid, node in node_by_id.items():
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
        if is_graph_dead_end(
            node,
            explicit_adj=explicit_adj,
            scoped_children=scoped_children,
            last_root_id=terminal_root_id,
        ):
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.GRAPH_DEAD_END_NODE,
                    message=f"Node {title!r} has no outgoing edges and is not a terminal node",
                    location=f"node.{nid}",
                )
            )


def check_variables(
    index: OrgStepIndex,
    scenario_vars: dict[str, Any],
    campaign_vars: dict[str, Any],
    result: ValidationResult,
) -> None:
    declared: set[str] = set(normalize_variable_map(scenario_vars).keys())
    declared |= set(normalize_variable_map(campaign_vars).keys())
    declared |= set(_BUILTIN_NAMES)

    for step, loc, sid in index.entries:
        config = _step_config(step)
        scan_root = {"config": config, **{k: v for k, v in step.items() if k != "config"}}
        base = f"step.{sid}" if sid else loc
        for var_name, ref_path in _scan_var_refs(scan_root, base):
            if var_name not in declared:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.UNDECLARED_VARIABLE,
                        message=f"${{{var_name}}} chưa được declared ở tầng nào",
                        location=ref_path,
                    )
                )
        stype = str(step.get("type") or "")
        if stype in ("variables_control.set_variable", "set_variable"):
            name = config.get("name") or step.get("name")
            if isinstance(name, str) and name:
                declared.add(name)


def check_on_error_targets(index: OrgStepIndex, result: ValidationResult) -> None:
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


def check_retry_config(index: OrgStepIndex, result: ValidationResult) -> None:
    for step, loc, sid in index.entries:
        retry = step.get("retry")
        if not isinstance(retry, dict):
            continue
        retry_loc = f"step.{sid}.retry" if sid else f"{loc}.retry"
        attempts = retry.get("attempts", retry.get("max_attempts", 1))
        try:
            max_attempts = int(attempts)
        except (TypeError, ValueError):
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.INVALID_RETRY_CONFIG,
                    message="retry.attempts must be an integer",
                    location=f"{retry_loc}.attempts",
                )
            )
            continue
        if max_attempts < 1:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.INVALID_RETRY_CONFIG,
                    message="retry.attempts must be at least 1",
                    location=f"{retry_loc}.attempts",
                )
            )
        elif max_attempts > 10:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.RETRY_MAX_ATTEMPTS_OUT_OF_RANGE,
                    message="retry.max_attempts must be between 1 and 10",
                    location=f"{retry_loc}.max_attempts",
                )
            )
        strategy = retry.get("backoff_strategy")
        if strategy is not None and str(strategy).lower() not in {"fixed", "exponential"}:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.RETRY_BACKOFF_INVALID,
                    message='retry.backoff_strategy must be "fixed" or "exponential"',
                    location=f"{retry_loc}.backoff_strategy",
                )
            )
        jitter = retry.get("jitter")
        if jitter is not None:
            try:
                jitter_num = float(jitter)
            except (TypeError, ValueError):
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.RETRY_BACKOFF_INVALID,
                        message="retry.jitter must be a number between 0 and 1",
                        location=f"{retry_loc}.jitter",
                    )
                )
            else:
                if jitter_num < 0 or jitter_num > 1:
                    result.add(
                        ValidationIssue(
                            level="error",
                            code=C.RETRY_BACKOFF_INVALID,
                            message="retry.jitter must be between 0 and 1",
                            location=f"{retry_loc}.jitter",
                        )
                    )
        reasons = retry.get("retryable_reasons")
        if reasons is not None and not isinstance(reasons, list):
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.INVALID_RETRY_CONFIG,
                    message="retry.retryable_reasons must be a list of strings",
                    location=f"{retry_loc}.retryable_reasons",
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
                        code=C.RETRY_BACKOFF_INVALID,
                        message=f"retry.{key} must be a positive number",
                        location=f"{retry_loc}.{key}",
                    )
                )
                continue
            if num < 0:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.RETRY_BACKOFF_INVALID,
                        message=f"retry.{key} must be positive",
                        location=f"{retry_loc}.{key}",
                    )
                )


def check_lint_warnings(
    index: OrgStepIndex,
    *,
    scenario_vars: dict[str, Any],
    campaign_vars: dict[str, Any],
    result: ValidationResult,
) -> None:
    validation_meta = (
        scenario_vars.get("_validation")
        if isinstance(scenario_vars.get("_validation"), dict)
        else {}
    )
    if not validation_meta.get("skip_no_verification"):
        if index.has_interaction and not index.has_verification:
            result.add(
                ValidationIssue(
                    level="warning",
                    code=C.NO_VERIFICATION_STEP,
                    message="scenario UI-gated khuyến nghị có ít nhất 1 verification",
                    location="scenario",
                    hint="Add a verification.* step or set variables._validation.skip_no_verification=true",
                )
            )

    camp = normalize_variable_map(campaign_vars)
    has_account_binding = bool(camp.get("__ACCOUNT_ID__") or camp.get("__ACCOUNT_GROUP_ID__"))
    if index.has_social and not has_account_binding:
        result.add(
            ValidationIssue(
                level="warning",
                code=C.IMPLICIT_ACCOUNT_FALLBACK,
                message="Social platform steps may use implicit primary-account fallback; set campaign __ACCOUNT_* vars",
                location="scenario",
            )
        )


class OrgScenarioValidationRefCache:
    """Batch-loaded org scenarios for reference resolution."""

    __slots__ = ("_by_id", "_versions", "_depth_limit")

    def __init__(
        self,
        rows: list[tuple[str, str, dict | None, str, int]],
        *,
        depth_limit: int,
    ) -> None:
        self._depth_limit = depth_limit
        self._by_id: dict[str, tuple[str, dict | None, str, int]] = {
            row_id: (kind, body, status, version)
            for row_id, kind, body, status, version in rows
        }
        self._versions: set[tuple[str, int]] = {
            (row_id, version) for row_id, _, _, _, version in rows
        }

    def register(
        self,
        scenario_id: str,
        *,
        kind: str,
        body: dict[str, Any] | None,
        status: str,
        version: int,
    ) -> None:
        self._by_id[scenario_id] = (kind, body, status, version)
        self._versions.add((scenario_id, version))

    def get(self, scenario_id: str) -> tuple[str, dict | None, str, int] | None:
        return self._by_id.get(scenario_id)

    def has_version(self, scenario_id: str, version: int) -> bool:
        return (scenario_id, version) in self._versions

    def steps_for(self, scenario_id: str) -> list[dict[str, Any]]:
        row = self._by_id.get(scenario_id)
        if row is None:
            return []
        kind, body, _, _ = row
        return steps_from_body(kind, body)


async def build_org_ref_cache(
    db,
    *,
    org_id: str,
    root_scenario_id: str,
    root_kind: str,
    root_body: dict[str, Any],
    root_status: str,
    root_version: int,
    depth_limit: int,
) -> OrgScenarioValidationRefCache:
    from db.crud import org_scenario as org_scenario_repo

    pending: set[str] = set()
    loaded: set[str] = {root_scenario_id}
    cache_rows: list[tuple[str, str, dict | None, str, int]] = []

    def collect_refs(scenario_id: str, kind: str, body: dict | None) -> None:
        for step in steps_from_body(kind, body):
            ref_id = extract_run_scenario_id(step)
            if ref_id and ref_id not in loaded:
                pending.add(ref_id)

    collect_refs(root_scenario_id, root_kind, root_body)
    for _ in range(depth_limit + 1):
        if not pending:
            break
        batch = sorted(pending)
        pending.clear()
        rows = await org_scenario_repo.get_org_scenario_refs_by_ids(db, org_id, batch)
        found = {row_id for row_id, _, _, _, _ in rows}
        cache_rows.extend(rows)
        for row_id, kind, body, _, _ in rows:
            loaded.add(row_id)
            collect_refs(row_id, kind, body)
        for missing in set(batch) - found:
            loaded.add(missing)

    cache = OrgScenarioValidationRefCache(cache_rows, depth_limit=depth_limit)
    cache.register(
        root_scenario_id,
        kind=root_kind,
        body=root_body,
        status=root_status,
        version=root_version,
    )
    return cache


def check_org_scenario_references(
    root_scenario_id: str,
    index: OrgStepIndex,
    *,
    ref_cache: OrgScenarioValidationRefCache,
    result: ValidationResult,
) -> None:
    depth_limit = ref_cache._depth_limit

    def walk(scenario_id: str, steps: list[dict[str, Any]], stack: list[str], depth: int) -> None:
        if depth > depth_limit:
            result.add(
                ValidationIssue(
                    level="error",
                    code=C.SCENARIO_DEPTH_EXCEEDED,
                    message=f"Nested scenario depth exceeds limit ({depth_limit})",
                    location="scenario",
                )
            )
            return

        sub_index = OrgStepIndex.build(steps)
        for step, loc, sid in sub_index.run_scenario_refs:
            config = _step_config(step)
            scenario_id_ref = str(config.get("scenario_id") or step.get("scenario_id") or "").strip()
            if not scenario_id_ref:
                continue
            loc_ref = f"step.{sid}" if sid else loc

            if scenario_id_ref in stack:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.CIRCULAR_SCENARIO_REFERENCE,
                        message=f"Circular scenario reference: {' -> '.join([*stack, scenario_id_ref])}",
                        location=loc_ref,
                    )
                )
                continue

            row = ref_cache.get(scenario_id_ref)
            if row is None:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.SCENARIO_REF_NOT_FOUND,
                        message=f"Referenced scenario not found: {scenario_id_ref!r}",
                        location=loc_ref,
                    )
                )
                continue

            kind, body, status, current_version = row
            if status == OrgScenarioStatus.ARCHIVED.value:
                result.add(
                    ValidationIssue(
                        level="error",
                        code=C.SCENARIO_REF_ARCHIVED,
                        message=f"Referenced scenario is archived: {scenario_id_ref!r}",
                        location=loc_ref,
                    )
                )

            version_raw = config.get("scenario_version", step.get("scenario_version"))
            if version_raw is not None:
                try:
                    version_num = int(version_raw)
                except (TypeError, ValueError):
                    result.add(
                        ValidationIssue(
                            level="error",
                            code=C.SCENARIO_VERSION_NOT_FOUND,
                            message=f"scenario_version must be an integer, got {version_raw!r}",
                            location=f"{loc_ref}.config.scenario_version",
                        )
                    )
                    continue
                if not ref_cache.has_version(scenario_id_ref, version_num):
                    result.add(
                        ValidationIssue(
                            level="error",
                            code=C.SCENARIO_VERSION_NOT_FOUND,
                            message=(
                                f"scenario_version {version_num} does not exist for scenario "
                                f"{scenario_id_ref!r} (current={current_version})"
                            ),
                            location=f"{loc_ref}.config.scenario_version",
                        )
                    )
                    continue

            sub_steps = steps_from_body(kind, body)
            walk(scenario_id_ref, sub_steps, [*stack, scenario_id_ref], depth + 1)

    root_steps = [step for step, _, _ in index.entries]
    walk(root_scenario_id, root_steps, [root_scenario_id], 0)
