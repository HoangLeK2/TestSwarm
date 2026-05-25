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


def test_normalize_xpath_at_sugar():
    step = {"type": "tap_selector", "by": "xpath", "value": "@com.app:id/login"}
    spec = normalize_step_selector(step)
    assert spec is not None
    assert "resource-id='com.app:id/login'" in (spec.value or "")
