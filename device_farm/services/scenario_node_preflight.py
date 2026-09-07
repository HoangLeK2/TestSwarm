"""Runtime preflight for scenario node capabilities."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from common.node_capabilities import node_capability_for
from services.execution.reason_codes import NODE_CAPABILITY_PREFLIGHT_FAILED

NODE_CAPABILITY_KEYS = (
    "has_u2",
    "has_stf",
    "has_ocr",
    "has_tesseract",
    "has_image_match",
    "has_opencv",
    "supports_advanced_gestures",
    "supports_clipboard",
    "supports_file_ops",
    "supports_install_apk",
    "supports_screenshot",
    "supports_shell",
)


@dataclass(frozen=True)
class NodeCapabilityIssue:
    path: str
    index: int
    step_type: str
    missing: tuple[str, ...]
    risk: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["missing"] = list(self.missing)
        return data


@dataclass(frozen=True)
class NodeCapabilityWarning:
    path: str
    index: int
    step_type: str
    unknown: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["unknown"] = list(self.unknown)
        return data


@dataclass(frozen=True)
class ScenarioNodePreflightResult:
    ok: bool
    issues: tuple[NodeCapabilityIssue, ...]
    warnings: tuple[NodeCapabilityWarning, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }

    @property
    def message(self) -> str:
        if self.ok:
            return "node capability preflight passed"
        first = self.issues[0]
        return (
            f"node capability preflight failed at {first.path} "
            f"({first.step_type}): missing {', '.join(first.missing)}"
        )


def scenario_node_preflight_error_payload(
    result: ScenarioNodePreflightResult,
) -> dict[str, Any]:
    return {
        "error": NODE_CAPABILITY_PREFLIGHT_FAILED,
        "message": result.message,
        "preflight": result.to_dict(),
    }


def scenario_node_preflight_failure_reason(
    result: ScenarioNodePreflightResult,
) -> str:
    return result.message


def scenario_from_scenario_registry(
    scenario_refs: Iterable[dict[str, Any]],
    scenario_registry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten dispatched scenario bodies for capability preflight.

    Campaign runtime executes top-level run_scenario wrappers. The actual device
    actions live in scenario_registry, so preflight must inspect those bodies.
    """
    registry = scenario_registry or {}
    by_id = registry.get("by_id") if isinstance(registry, dict) else {}
    if not isinstance(by_id, dict):
        by_id = {}
    steps: list[dict[str, Any]] = []
    for ref in scenario_refs:
        if not isinstance(ref, dict):
            continue
        scenario_id = str(ref.get("scenario_id") or "")
        entry = by_id.get(scenario_id)
        if not isinstance(entry, dict):
            continue
        entry_steps = entry.get("steps")
        if isinstance(entry_steps, list):
            steps.extend(step for step in entry_steps if isinstance(step, dict))
    return {"steps": steps}


def preflight_scenario_registry_node_capabilities(
    device: Any,
    scenario_refs: Iterable[dict[str, Any]],
    scenario_registry: dict[str, Any] | None,
) -> ScenarioNodePreflightResult:
    return preflight_scenario_node_capabilities(
        device,
        scenario_from_scenario_registry(scenario_refs, scenario_registry),
    )


def _iter_steps(steps: Iterable[Any], path: str = "steps") -> Iterable[tuple[str, int, dict[str, Any]]]:
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            continue
        current_path = f"{path}[{index}]"
        yield current_path, index, raw_step

        for key in ("steps", "then", "else", "completion_steps"):
            nested = raw_step.get(key)
            if isinstance(nested, list):
                yield from _iter_steps(nested, f"{current_path}.{key}")

        branches = raw_step.get("branches")
        if isinstance(branches, list):
            for branch_index, branch in enumerate(branches):
                if not isinstance(branch, dict):
                    continue
                branch_steps = branch.get("steps")
                if isinstance(branch_steps, list):
                    yield from _iter_steps(
                        branch_steps,
                        f"{current_path}.branches[{branch_index}].steps",
                    )


def _relay_capabilities_for_serial(serial: str) -> dict[str, Any]:
    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        relay = get_relay_manager()
        if relay is None:
            return {}
        caps = relay.get_capabilities(serial)
        return dict(caps or {}) if isinstance(caps, dict) else {}
    except Exception:
        return {}


def _relay_capabilities(device: Any, serial: str | None = None) -> dict[str, Any]:
    resolve = getattr(device, "_resolve_relay_serial", None)
    relay_serial = resolve() if callable(resolve) else (serial or getattr(device, "serial", ""))
    return _relay_capabilities_for_serial(str(relay_serial or ""))


def _bool_method(device: Any, name: str) -> bool | None:
    method = getattr(device, name, None)
    if not callable(method):
        return None
    try:
        return bool(method())
    except Exception:
        return False


def _device_capability_value(device: Any, capabilities: dict[str, Any], name: str) -> bool | None:
    if name in capabilities:
        return bool(capabilities.get(name))

    if name == "has_ocr":
        return _bool_method(device, "ocr_supported")
    if name == "has_tesseract":
        return _bool_method(device, "ocr_supported")
    if name == "has_image_match":
        return _bool_method(device, "image_match_supported")
    if name == "has_opencv":
        return _bool_method(device, "image_match_supported")

    if name == "has_u2":
        return True if getattr(device, "u2", None) is not None else None
    if name == "has_stf":
        return True if getattr(device, "stf", None) is not None else None

    if name == "supports_clipboard":
        return True if callable(getattr(device, "set_clipboard", None)) else None
    if name == "supports_file_ops":
        return (
            True
            if callable(getattr(device, "push_file", None))
            and callable(getattr(device, "pull_file", None))
            else None
        )
    if name == "supports_install_apk":
        return True if callable(getattr(device, "install", None)) else None
    if name == "supports_screenshot":
        return True if callable(getattr(device, "take_screenshot", None)) else None
    if name == "supports_shell":
        return True if callable(getattr(device, "shell", None)) else None
    if name == "supports_advanced_gestures":
        has_u2 = _device_capability_value(device, capabilities, "has_u2")
        if has_u2 is True:
            return True
        return None

    return None


def collect_node_capabilities(device: Any | None, serial: str | None = None) -> dict[str, bool]:
    """Return only runtime capability keys whose value is known for this device."""
    capabilities = _relay_capabilities(device, serial) if device is not None else _relay_capabilities_for_serial(serial or "")
    known: dict[str, bool] = {}
    for key in NODE_CAPABILITY_KEYS:
        value = _device_capability_value(device, capabilities, key)
        if value is not None:
            known[key] = value
    return known


def _contains_ocr_near(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (key == "ocr_near" and bool(item))
            or _contains_ocr_near(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_ocr_near(item) for item in value)
    return False


def _step_capability_requirements(step: dict[str, Any], scenario: dict[str, Any]) -> tuple[str, ...]:
    step_type = str(step.get("type") or "")
    capability = node_capability_for(step_type)
    requirements = list(capability.requires)

    if step_type == "tap":
        has_selector = bool(step.get("selector") or step.get("by") or step.get("value"))
        has_visual_anchor = bool((step.get("screen") or {}).get("screenshot_anchor"))
        requirements = []
        if has_selector:
            requirements.append("has_u2")
        if has_visual_anchor:
            requirements.extend(["has_image_match", "has_opencv"])

    if step_type in {"login_if_needed", "fill_form", "assert_app_state"}:
        profile = (
            step.get("profile")
            or step.get("app_automation_profile")
            or scenario.get("app_automation_profile")
            or scenario.get("automation_profile")
        )
        if _contains_ocr_near(profile):
            requirements.extend(["has_ocr", "has_tesseract"])

    return tuple(dict.fromkeys(requirements))


def preflight_scenario_node_capabilities(
    device: Any,
    scenario: dict[str, Any],
) -> ScenarioNodePreflightResult:
    capabilities = _relay_capabilities(device)
    return preflight_scenario_node_capabilities_for_capabilities(
        capabilities,
        scenario,
        device=device,
    )


def preflight_scenario_node_capabilities_for_capabilities(
    capabilities: dict[str, Any],
    scenario: dict[str, Any],
    *,
    device: Any | None = None,
) -> ScenarioNodePreflightResult:
    issues: list[NodeCapabilityIssue] = []
    warnings: list[NodeCapabilityWarning] = []
    steps = scenario.get("steps") if isinstance(scenario, dict) else []

    for path, index, step in _iter_steps(steps if isinstance(steps, list) else []):
        step_type = str(step.get("type") or "")
        if not step_type:
            continue
        requirements = _step_capability_requirements(step, scenario)
        if not requirements:
            continue
        capability = node_capability_for(step_type)
        missing: list[str] = []
        unknown: list[str] = []
        for required in requirements:
            value = _device_capability_value(device, capabilities, required)
            if value is False:
                missing.append(required)
            elif value is None:
                unknown.append(required)
        if missing:
            issues.append(
                NodeCapabilityIssue(
                    path=path,
                    index=index,
                    step_type=step_type,
                    missing=tuple(missing),
                    risk=capability.risk,
                )
            )
        if unknown:
            warnings.append(
                NodeCapabilityWarning(
                    path=path,
                    index=index,
                    step_type=step_type,
                    unknown=tuple(unknown),
                )
            )

    return ScenarioNodePreflightResult(
        ok=not issues,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )
