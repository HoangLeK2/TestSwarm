"""Fail-closed policy decisions for customer-controlled device operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


_FORBIDDEN_ACTION_PREFIXES = (
    "commerce.",
    "advertising.click",
    "auth.otp_bypass",
    "permission.escalate",
    "production.mutate",
)
_DEVICE_MUTATION_STEP_TYPES = frozenset(
    {
        "adb_shell",
        "clear_app",
        "dismiss_popup",
        "double_tap",
        "drag",
        "fill_form",
        "input_text",
        "input_selector",
        "install_apk",
        "key",
        "launch_app",
        "login_if_needed",
        "long_tap_selector",
        "open_url",
        "pinch",
        "push_file",
        "run_scenario",
        "scroll_down",
        "scroll_to",
        "set_clipboard",
        "stop_app",
        "swipe",
        "swipe_ratio",
        "tap",
        "tap_image",
        "tap_position",
        "tap_ratio",
        "tap_selector",
        "tap_xml_match",
    }
)


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    version: str
    app_package: str
    allowed_actions: frozenset[str]
    allowed_targets: frozenset[str]


@dataclass(frozen=True, slots=True)
class OperationRequest:
    primitive: str
    semantic_action: str
    target: str | None
    observed_package: str | None
    approval_policy_version: str
    untrusted_ui_text: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: str
    path: str | None = None


def evaluate_operation(
    policy: OperationPolicy,
    request: OperationRequest,
) -> PolicyDecision:
    """Evaluate one operation using only the server-loaded policy and trusted context."""
    if request.approval_policy_version != policy.version:
        return PolicyDecision(False, "STALE_POLICY_APPROVAL")
    if request.observed_package != policy.app_package:
        return PolicyDecision(False, "PACKAGE_SCOPE_MISMATCH")
    if request.semantic_action.startswith(_FORBIDDEN_ACTION_PREFIXES):
        return PolicyDecision(False, "FORBIDDEN_ACTION")
    if request.semantic_action not in policy.allowed_actions:
        return PolicyDecision(False, "ACTION_NOT_APPROVED")
    if not request.target:
        return PolicyDecision(False, "AMBIGUOUS_TARGET")
    if request.target not in policy.allowed_targets:
        return PolicyDecision(False, "TARGET_NOT_APPROVED")
    return PolicyDecision(True, "ALLOWED")


def _walk_steps(steps: list[Any], prefix: str = "steps") -> Iterator[tuple[str, dict[str, Any]]]:
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            continue
        path = f"{prefix}[{index}]"
        yield path, raw_step
        for child_key in ("steps", "then", "else"):
            children = raw_step.get(child_key)
            if isinstance(children, list):
                yield from _walk_steps(children, f"{path}.{child_key}")
        branches = raw_step.get("branches")
        if isinstance(branches, list):
            for branch_index, branch in enumerate(branches):
                if not isinstance(branch, dict):
                    continue
                children = branch.get("steps")
                if isinstance(children, list):
                    yield from _walk_steps(
                        children,
                        f"{path}.branches[{branch_index}].steps",
                    )


def evaluate_scenario_operations(
    policy: OperationPolicy,
    scenario: dict[str, Any],
    *,
    observed_package: str | None,
    approval_policy_version: str,
) -> tuple[PolicyDecision, ...]:
    """Return every fail-closed policy violation in a nested scenario."""
    violations: list[PolicyDecision] = []
    steps = scenario.get("steps")
    if not isinstance(steps, list):
        return (PolicyDecision(False, "SCENARIO_STEPS_INVALID", "steps"),)

    for path, step in _walk_steps(steps):
        primitive = str(step.get("type") or "")
        if primitive not in _DEVICE_MUTATION_STEP_TYPES:
            continue
        semantic_action = str(step.get("semantic_action") or "")
        target = step.get("policy_target")
        if primitive == "launch_app":
            semantic_action = semantic_action or "navigation.open"
            target = target or step.get("package")
        decision = evaluate_operation(
            policy,
            OperationRequest(
                primitive=primitive,
                semantic_action=semantic_action,
                target=str(target) if target else None,
                observed_package=observed_package,
                approval_policy_version=approval_policy_version,
            ),
        )
        if not decision.allowed:
            violations.append(
                PolicyDecision(False, decision.reason_code, path)
            )
    return tuple(violations)
