from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CATALOG_SCHEMA_VERSION = 1


NODE_FIELD_METADATA: dict[str, dict[str, dict[str, Any]]] = {
    "launch_app": {
        "package": {"type": "string", "label_key": "appLifecycle.packageLabel"},
        "wait_after": {
            "type": "number",
            "default": 2,
            "min": 0,
            "max": 30,
            "label_key": "appLifecycle.waitAfterLaunch",
        },
        "activity": {
            "type": "string",
            "label_key": "appLifecycle.activityLabel",
            "placeholder_key": "appLifecycle.activityPlaceholder",
        },
        "component": {"type": "string"},
        "stop_before": {
            "type": "boolean",
            "default": False,
            "label_key": "appLifecycle.stopBefore",
        },
        "use_monkey": {
            "type": "boolean",
            "default": False,
            "label_key": "appLifecycle.useMonkey",
        },
    },
    "stop_app": {
        "package": {"type": "string", "label_key": "appLifecycle.packageLabel"},
    },
    "clear_app": {
        "package": {"type": "string", "label_key": "appLifecycle.packageLabel"},
    },
    "wait_app": {
        "package": {"type": "string", "label_key": "appLifecycle.packageLabel"},
        "timeout": {
            "type": "number",
            "default": 20,
            "min": 0.1,
            "max": 120,
            "label_key": "appLifecycle.timeoutSeconds",
        },
        "front": {
            "type": "boolean",
            "default": True,
            "label_key": "appLifecycle.waitForeground",
        },
    },
    "open_url": {
        "url": {"type": "string", "pattern": "^https?://"},
        "package": {"type": "string", "label_key": "stepFields.browserPackage"},
    },
    "install_apk": {
        "url": {
            "type": "string",
            "label_key": "appLifecycle.installApkUrlLabel",
            "placeholder_key": "appLifecycle.installApkUrlPlaceholder",
        },
        "timeout": {
            "type": "number",
            "default": 90,
            "min": 10,
            "max": 600,
            "label_key": "appLifecycle.installApkTimeoutLabel",
        },
    },
    "wait": {
        "seconds": {
            "type": "number",
            "default": 1,
            "min": 0,
            "label_key": "stepFields.durationSeconds",
        },
    },
    "tap_position": {
        "pos": {
            "type": "enum",
            "values": [
                {"value": "top_center", "label_key": "stepFields.posTopCenter"},
                {"value": "middle_center", "label_key": "stepFields.posMiddleCenter"},
                {"value": "bottom_center", "label_key": "stepFields.posBottomCenter"},
                {"value": "search_bar", "label_key": "stepFields.posSearchBar"},
            ],
            "label_key": "stepFields.position",
        },
    },
    "key": {
        "key": {"type": "string", "label_key": "stepFields.key"},
    },
    "adb_shell": {
        "command": {"type": "string", "label_key": "adbShell.commandLabel"},
        "timeout": {
            "type": "number",
            "default": 30,
            "min": 1,
            "max": 120,
            "label_key": "adbShell.timeoutLabel",
        },
        "fail_on_error": {
            "type": "boolean",
            "default": True,
            "label_key": "adbShell.failOnErrorLabel",
        },
        "save_as": {"type": "string", "label_key": "adbShell.saveAsLabel"},
        "max_output_chars": {
            "type": "number",
            "default": 8000,
            "min": 1000,
            "max": 50000,
            "label_key": "adbShell.maxOutputLabel",
        },
    },
    # Partial on purpose: count / while / max_iterations stay with the editor's
    # LoopConfigFields, which has a count-vs-while mode toggle and a condition
    # builder that a generic form cannot match. Declared here are the fields
    # that had no editor at all — stall_after and idle_delay_seconds are the
    # guards against a loop grinding on a screen it cannot act on, and
    # stall_after defaults to 0 (off), so they were unreachable from the UI.
    # Bounds mirror control_flow.py:_handle_loop.
    # Do not add count/while/max_iterations here: they would then render twice.
    "loop": {
        # count_min/count_max override count, so they belong next to it — but
        # LoopConfigFields owns count and cannot render a range, so they come
        # through here instead. Both must be set or the step fails as a config
        # error; a half-configured range is a typo, not a shorthand.
        "count_min": {
            "type": "number",
            "min": 0,
            "label_key": "controlFlow.loopCountMinLabel",
        },
        "count_max": {
            "type": "number",
            "min": 0,
            "label_key": "controlFlow.loopCountMaxLabel",
        },
        "delay_between_min": {
            "type": "number",
            "min": 0,
            "max": 300,
            "label_key": "controlFlow.loopDelayMinLabel",
        },
        "delay_between_max": {
            "type": "number",
            "min": 0,
            "max": 300,
            "label_key": "controlFlow.loopDelayMaxLabel",
        },
        "duration_seconds": {
            "type": "number",
            "min": 0,
            "label_key": "controlFlow.loopDurationSecondsLabel",
        },
        "stall_after": {
            "type": "number",
            "default": 0,
            "min": 0,
            "label_key": "controlFlow.loopStallAfterLabel",
        },
        "idle_delay_seconds": {
            "type": "number",
            "default": 0,
            "min": 0,
            "max": 300,
            "advanced": True,
            "label_key": "controlFlow.loopIdleDelayLabel",
        },
        "loop_var": {
            "type": "string",
            "advanced": True,
            "label_key": "controlFlow.loopVarLabel",
        },
    },
}


def apply_node_catalog_metadata(
    step_schema: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Attach catalog-owned field metadata to the legacy step schema."""
    merged: dict[str, dict[str, Any]] = {}
    for step_type, schema in step_schema.items():
        entry = dict(schema)
        fields = NODE_FIELD_METADATA.get(step_type)
        if fields:
            entry["fields"] = {
                field_name: dict(field_spec)
                for field_name, field_spec in fields.items()
            }
        else:
            entry.pop("fields", None)
        merged[step_type] = entry
    return merged


@dataclass(frozen=True, slots=True)
class NodeFieldSchema:
    name: str
    type: str
    label: str
    group: str
    required: bool = False
    advanced: bool = False
    description: str = ""
    placeholder: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    visible_when: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NodePreset:
    id: str
    display_name: str
    description: str
    runtime_step_type: str
    defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    node_type: str
    runtime_step_type: str
    schema_version: int
    display_name: str
    description: str
    category: str
    capability_id: str | None = None
    fields: list[NodeFieldSchema] = field(default_factory=list)
    presets: list[NodePreset] = field(default_factory=list)
    legacy: dict[str, Any] = field(default_factory=dict)


def _catalog_definitions() -> list[NodeDefinition]:
    return []


def _display_name(step_type: str) -> str:
    return step_type.replace("_", " ").title()


def _category_for(step_type: str) -> str:
    if step_type in {"repeat", "repeat_until", "if_element", "if_variable", "loop", "break_if", "random_pick", "run_scenario"}:
        return "Control Flow"
    if step_type in {"set_variable", "extract", "save_extraction"} or step_type.startswith("extract_"):
        return "Data"
    if step_type in {"launch_app", "stop_app", "clear_app", "wait_app", "install_apk", "open_url"}:
        return "App"
    return "Device"


def _catalog_field(name: str, spec: dict[str, Any], *, required: bool) -> dict[str, Any]:
    field_spec = dict(spec)
    return {
        "name": name,
        "type": field_spec.pop("type", "string"),
        "label": name.replace("_", " ").title(),
        "group": "required" if required else "options",
        "required": required,
        "advanced": bool(field_spec.pop("advanced", False)),
        **field_spec,
    }


def _node_from_schema(step_type: str, schema: dict[str, Any]) -> dict[str, Any]:
    required = set(schema.get("required") or [])
    fields = [
        _catalog_field(name, spec, required=name in required)
        for name, spec in NODE_FIELD_METADATA.get(step_type, {}).items()
    ]
    return {
        "node_type": step_type,
        "runtime_step_type": step_type,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "display_name": _display_name(step_type),
        "description": str(schema.get("description") or ""),
        "category": _category_for(step_type),
        "required": list(schema.get("required") or []),
        "optional": list(schema.get("optional") or []),
        "required_any": list(schema.get("required_any") or []),
        "fields": fields,
        "defaults": {
            name: spec["default"]
            for name, spec in NODE_FIELD_METADATA.get(step_type, {}).items()
            if "default" in spec
        },
        "presets": [],
        "legacy": {},
    }


def _merge_catalog_nodes(
    step_types: list[str] | None,
    step_schema: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    explicit = {
        definition.node_type: asdict(definition)
        for definition in _catalog_definitions()
    }
    if not step_types or step_schema is None:
        return list(explicit.values())

    nodes: list[dict[str, Any]] = []
    for step_type in step_types:
        node = _node_from_schema(step_type, step_schema.get(step_type) or {})
        if step_type in explicit:
            node = {**node, **explicit[step_type]}
            schema = step_schema.get(step_type) or {}
            node["description"] = str(schema.get("description") or node.get("description") or "")
            node["required"] = list(schema.get("required") or [])
            node["optional"] = list(schema.get("optional") or [])
            node["required_any"] = list(schema.get("required_any") or [])
        nodes.append(node)
    return nodes


def build_node_catalog(
    registry: Any | None = None,
    *,
    step_types: list[str] | None = None,
    step_schema: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "execution_model": "deterministic_sequence",
        "nodes": _merge_catalog_nodes(step_types, step_schema),
        "providers": [],
    }
