"""Capability metadata for scenario nodes.

This registry is intentionally static and cheap to import. It gives the editor,
schema endpoint, and contract tests one backend-owned source for what a node
needs from the device/agent and what evidence a recorder should preserve.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


NodeGroup = Literal["action", "control", "variable"]
NodeRisk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class NodeCapability:
    type: str
    group: NodeGroup = "action"
    risk: NodeRisk = "low"
    requires: tuple[str, ...] = ()
    surfaces: tuple[str, ...] = ("schema",)
    recorder_evidence: tuple[str, ...] = ()
    inspector_hints: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requires"] = list(self.requires)
        data["surfaces"] = list(self.surfaces)
        data["recorder_evidence"] = list(self.recorder_evidence)
        data["inspector_hints"] = list(self.inspector_hints)
        return data


_CONTROL_NODES = {
    "repeat",
    "repeat_until",
    "if_element",
    "if_variable",
    "loop",
    "break_if",
    "random_pick",
    "run_scenario",
}

_VARIABLE_NODES = {
    "set_variable",
    "set_var",
    "extract",
    "extract_text_hierarchy",
    "extract_text_ocr",
    "extract_text_ai",
    "extract_screen_data",
    "save_extraction",
}

_HIGH_RISK_NODES = {
    "adb_shell",
    "clear_app",
    "install_apk",
    "stop_app",
}

_MEDIUM_RISK_NODES = {
    "connection_request",
    "community_membership",
    "content_interaction",
    "push_file",
    "pull_file",
    "set_clipboard",
    "social_connect_visible_people",
    "social_scan_posts_interact",
}

_REQUIRES: dict[str, tuple[str, ...]] = {
    "adb_shell": ("supports_shell",),
    "assert_app_state": ("has_u2",),
    "assert_element": ("has_u2",),
    "clear_app": ("supports_shell",),
    "dismiss_popup": ("has_u2",),
    "double_tap": ("supports_advanced_gestures",),
    "drag": ("supports_advanced_gestures",),
    "extract_text_ocr": ("has_ocr", "has_tesseract"),
    "fill_form": ("has_u2",),
    "if_element": ("has_u2",),
    "input_selector": ("has_u2",),
    "install_apk": ("supports_install_apk",),
    "launch_app": ("supports_shell",),
    "login_if_needed": ("has_u2",),
    "long_tap_selector": ("has_u2",),
    "pinch": ("supports_advanced_gestures",),
    "pull_file": ("supports_file_ops",),
    "push_file": ("supports_file_ops",),
    "scroll_to": ("has_u2",),
    "set_clipboard": ("supports_clipboard",),
    "social_connect_visible_people": ("has_u2",),
    "social_find_comment_button": ("has_u2",),
    "social_open_author_from_post_match": ("has_u2",),
    "social_open_commenter_from_post_match": ("has_u2",),
    "social_open_comments": ("has_u2",),
    "social_scan_posts_interact": ("has_u2",),
    "social_select_target": ("has_u2",),
    "social_sync_connections": ("has_u2",),
    "take_screenshot": ("supports_screenshot",),
    "tap": ("has_u2",),
    "tap_image": ("has_image_match", "has_opencv"),
    "tap_selector": ("has_u2",),
    "tap_xml_match": ("has_u2",),
    "verify_screen": ("has_image_match", "has_opencv"),
    "wait_element": ("has_u2",),
    "wait_stable": ("supports_screenshot",),
}

_RECORDER_EVIDENCE: dict[str, tuple[str, ...]] = {
    "assert_app_state": ("hierarchy_xml", "screenshot"),
    "extract_text_ocr": ("ocr_boxes", "screenshot_on_empty"),
    "tap": ("selector", "fallback_ratio", "screen_hash", "image_anchor"),
    "tap_image": ("template_key", "match_score", "match_bounds"),
    "tap_selector": ("selector", "fallback_ratio"),
    "tap_xml_match": ("hierarchy_xml", "matched_bounds"),
    "verify_screen": ("template_key", "match_score", "screen_hash"),
    "wait_element": ("selector", "timeout"),
}

_INSPECTOR_HINTS: dict[str, tuple[str, ...]] = {
    "extract_text_ocr": ("show_ocr_overlay",),
    "tap_image": ("show_template_match",),
    "tap_xml_match": ("show_hierarchy_match",),
    "verify_screen": ("show_template_match",),
}

_SURFACES: dict[str, tuple[str, ...]] = {
    "extract_text_ocr": ("schema", "api_schema", "executor", "agent_ocr"),
    "tap_image": ("schema", "api_schema", "executor", "agent_image_match"),
    "install_apk": ("schema", "api_schema", "executor", "frontend"),
}


def _group_for(step_type: str) -> NodeGroup:
    if step_type in _CONTROL_NODES:
        return "control"
    if step_type in _VARIABLE_NODES:
        return "variable"
    return "action"


def _risk_for(step_type: str) -> NodeRisk:
    if step_type in _HIGH_RISK_NODES:
        return "high"
    if step_type in _MEDIUM_RISK_NODES:
        return "medium"
    return "low"


def node_capability_for(step_type: str, *, description: str = "") -> NodeCapability:
    return NodeCapability(
        type=step_type,
        group=_group_for(step_type),
        risk=_risk_for(step_type),
        requires=_REQUIRES.get(step_type, ()),
        surfaces=_SURFACES.get(step_type, ("schema", "api_schema", "executor")),
        recorder_evidence=_RECORDER_EVIDENCE.get(step_type, ()),
        inspector_hints=_INSPECTOR_HINTS.get(step_type, ()),
        description=description,
    )


def build_node_capability_registry(
    step_types: list[str],
    step_schema: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    schema = step_schema or {}
    return [
        node_capability_for(
            step_type,
            description=str((schema.get(step_type) or {}).get("description") or ""),
        ).to_dict()
        for step_type in step_types
    ]


def find_node_contract_gaps(
    step_types: list[str],
    step_schema: dict[str, dict[str, Any]],
    registered_handlers: set[str] | None = None,
) -> dict[str, list[str]]:
    handlers = registered_handlers or set()
    return {
        "missing_schema": [
            step_type for step_type in step_types if step_type not in step_schema
        ],
        "missing_handler": [
            step_type
            for step_type in step_types
            if step_type not in handlers and step_type not in _CONTROL_NODES
        ],
    }
