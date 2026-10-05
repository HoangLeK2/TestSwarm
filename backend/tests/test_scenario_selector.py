"""Tests for services.scenario_selector."""
from __future__ import annotations

import pytest

from services.scenario_selector import (
    ScenarioSelectorSpec,
    compile_chain_to_xpath,
    normalize_step_selector,
    spec_has_chain,
    spec_to_agent_payload,
    spec_to_rpc_selector,
)


def test_normalize_legacy_flat():
    step = {"type": "tap_selector", "by": "text", "value": "OK"}
    spec = normalize_step_selector(step)
    assert spec is not None
    assert spec.by == "text"
    assert spec.value == "OK"


def test_normalize_nested_selector():
    step = {
        "type": "tap_selector",
        "selector": {
            "by": "text",
            "value": "Clock",
            "conditions": {"className": "android.widget.TextView"},
        },
    }
    spec = normalize_step_selector(step)
    assert spec is not None
    assert spec.conditions.get("className") == "android.widget.TextView"


def test_normalize_description_startswith_legacy_case():
    step = {
        "type": "tap_selector",
        "selector": {"by": "descriptionStartswith", "value": "Nút Thích"},
    }
    spec = normalize_step_selector(step)
    assert spec is not None
    assert spec.by == "descriptionStartswith"
    assert spec.value == "Nút Thích"


def test_spec_to_rpc_description_startswith_alias():
    spec = ScenarioSelectorSpec(by="descriptionStartswith", value="Nút Thích")
    rpc = spec_to_rpc_selector(spec)
    assert rpc.get("descriptionStartsWith") == "Nút Thích"
    assert rpc["mask"] & 0x200


def test_spec_to_rpc_description_contains():
    spec = ScenarioSelectorSpec(by="descriptionContains", value="Thích")
    rpc = spec_to_rpc_selector(spec)
    assert rpc.get("descriptionContains") == "Thích"
    assert rpc["mask"] & 0x80


def test_spec_to_rpc_multi_condition():
    spec = ScenarioSelectorSpec(
        by="text",
        value="Clock",
        conditions={"className": "android.widget.TextView"},
    )
    rpc = spec_to_rpc_selector(spec)
    assert "mask" in rpc
    assert rpc.get("text") == "Clock"
    assert rpc.get("className") == "android.widget.TextView"


def test_spec_to_rpc_instance():
    spec = ScenarioSelectorSpec(by="text", value="Add new", instance=1)
    rpc = spec_to_rpc_selector(spec)
    assert rpc.get("instance") == 1
    assert rpc["mask"] & 0x1000000


def test_spec_has_chain():
    spec = ScenarioSelectorSpec(
        by="text",
        value="Wi-Fi",
        chain={"op": "relative", "direction": "right", "target": {"by": "class name", "value": "android.widget.Switch"}},
    )
    assert spec_has_chain(spec)


def test_compile_chain_relative_xpath():
    spec = ScenarioSelectorSpec(
        by="text",
        value="Wi-Fi",
        chain={"op": "relative", "direction": "right", "target": {"className": "android.widget.Switch"}},
    )
    xp = compile_chain_to_xpath(spec)
    assert xp is not None
    assert "Wi" in xp or "Wi-Fi" in xp


def test_spec_to_agent_payload():
    spec = ScenarioSelectorSpec(by="resource-id", value="com.app:id/btn", instance=0)
    payload = spec_to_agent_payload(spec)
    assert payload["by"] == "resource-id"
    assert payload["instance"] == 0


def test_pydantic_nested_selector_validates():
    from api.schemas.scenario import TapSelectorStep

    step = TapSelectorStep.model_validate({
        "type": "tap_selector",
        "selector": {"by": "text", "value": "Login"},
        "timeout": 8,
    })
    assert step.selector is not None
    assert step.selector.value == "Login"


def test_pydantic_selector_conditions_description_startswith_validates():
    from api.schemas.scenario import TapSelectorStep

    step = TapSelectorStep.model_validate({
        "type": "tap_selector",
        "selector": {
            "by": "description",
            "value": "ignored",
            "conditions": {"descriptionStartsWith": "Nút Thích"},
        },
        "timeout": 8,
    })
    assert step.selector is not None
    assert step.selector.conditions is not None
    assert step.selector.conditions.descriptionStartsWith == "Nút Thích"


def test_node_matches_description_fuzzy_selectors():
    from tasks.scenario.utils import _node_matches_selector

    class Node:
        def get(self, key, default=None):
            if key == "content-desc":
                return "Nút Thích bình luận của Hoàng"
            return default

    node = Node()
    assert _node_matches_selector(node, "descriptionContains", "bình luận")
    assert _node_matches_selector(node, "descriptionStartsWith", "Nút Thích")
    assert _node_matches_selector(node, "descriptionStartswith", "Nút Thích")


def test_normalize_xpath_at_sugar():
    step = {"type": "tap_selector", "by": "xpath", "value": "@com.app:id/login"}
    spec = normalize_step_selector(step)
    assert spec is not None
    assert "resource-id='com.app:id/login'" in (spec.value or "")
