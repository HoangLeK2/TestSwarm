from __future__ import annotations

"""
tests/test_variable_resolver.py — Unit tests cho VariableContext.

Run: pytest tests/test_variable_resolver.py -v
"""

import os
import re

import pytest

from common.variable_resolver import VariableContext, normalize_device_vars



def test_basic_string_interpolation():
    ctx = VariableContext(scenario_vars={"NAME": "Alice"})
    assert ctx.resolve("Hello ${NAME}") == "Hello Alice"


def test_full_match_returns_raw_type_int():
    ctx = VariableContext(scenario_vars={"TIMEOUT": 5})
    result = ctx.resolve("${TIMEOUT}")
    assert result == 5
    assert isinstance(result, int)


def test_full_match_returns_raw_type_float():
    ctx = VariableContext(scenario_vars={"RATIO": 0.75})
    result = ctx.resolve("${RATIO}")
    assert result == 0.75
    assert isinstance(result, float)


def test_multiple_vars_in_one_string():
    ctx = VariableContext(scenario_vars={"A": "foo", "B": "bar"})
    assert ctx.resolve("${A}/${B}") == "foo/bar"


def test_undefined_var_passthrough():
    ctx = VariableContext()
    assert ctx.resolve("${UNDEFINED}") == "${UNDEFINED}"


def test_undefined_var_in_partial_string():
    ctx = VariableContext(scenario_vars={"NAME": "Alice"})
    assert ctx.resolve("Hi ${NAME} and ${OTHER}") == "Hi Alice and ${OTHER}"



def test_list_random_pick_in_full_match(monkeypatch):
    monkeypatch.setattr("common.variable_resolver.random.choice", lambda lst: lst[0])
    ctx = VariableContext(scenario_vars={"X": ["a", "b", "c"]})
    assert ctx.resolve("${X}") == "a"


def test_list_random_pick_in_partial_string(monkeypatch):
    monkeypatch.setattr("common.variable_resolver.random.choice", lambda lst: lst[-1])
    ctx = VariableContext(scenario_vars={"X": ["a", "b", "c"]})
    result = ctx.resolve("value=${X}")
    assert result == "value=c"


def test_list_random_pick_returns_one_of_values():
    ctx = VariableContext(scenario_vars={"X": ["a", "b", "c"]})
    for _ in range(20):
        result = ctx.resolve("${X}")
        assert result in ["a", "b", "c"]



def test_nested_dict():
    ctx = VariableContext(scenario_vars={"A": "1", "B": "2"})
    result = ctx.resolve({"x": "${A}", "y": "${B}"})
    assert result == {"x": "1", "y": "2"}


def test_nested_list():
    ctx = VariableContext(scenario_vars={"V": "hello"})
    result = ctx.resolve(["${V}", "literal", "${V}"])
    assert result == ["hello", "literal", "hello"]


def test_non_string_passthrough():
    ctx = VariableContext()
    assert ctx.resolve(42) == 42
    assert ctx.resolve(3.14) == 3.14
    assert ctx.resolve(True) is True
    assert ctx.resolve(None) is None


def test_dict_keys_not_resolved():
    ctx = VariableContext(scenario_vars={"K": "newkey"})
    result = ctx.resolve({"${K}": "value"})
    # Keys không được resolve, chỉ values
    assert "${K}" in result



def test_runtime_overrides_scenario():
    ctx = VariableContext(scenario_vars={"X": "scenario"})
    ctx.set("X", "runtime")
    assert ctx.resolve("${X}") == "runtime"


def test_scenario_overrides_campaign():
    ctx = VariableContext(
        scenario_vars={"X": "scenario"},
        campaign_vars={"X": "campaign"},
    )
    assert ctx.resolve("${X}") == "scenario"


def test_campaign_used_when_no_scenario_var():
    ctx = VariableContext(campaign_vars={"BRAND": "TestBrand"})
    assert ctx.resolve("${BRAND}") == "TestBrand"


def test_env_fallback(monkeypatch):
    monkeypatch.setenv("MY_FARM_VAR", "from_env")
    ctx = VariableContext(env_whitelist=frozenset({"MY_FARM_VAR"}))
    assert ctx.resolve("${MY_FARM_VAR}") == "from_env"


def test_env_not_used_when_scenario_has_var(monkeypatch):
    monkeypatch.setenv("MY_VAR", "from_env")
    ctx = VariableContext(scenario_vars={"MY_VAR": "from_scenario"})
    assert ctx.resolve("${MY_VAR}") == "from_scenario"



def test_set_and_resolve():
    ctx = VariableContext()
    ctx.set("FOO", "bar")
    assert ctx.resolve("${FOO}") == "bar"


def test_set_overrides_scenario():
    ctx = VariableContext(scenario_vars={"X": "old"})
    ctx.set("X", "new")
    assert ctx.resolve("${X}") == "new"


def test_set_from_list():
    ctx = VariableContext()
    chosen = ctx.set_from_list("COLOR", ["red", "green", "blue"])
    assert chosen in ["red", "green", "blue"]
    assert ctx.resolve("${COLOR}") == chosen


def test_increment_starts_at_zero():
    ctx = VariableContext()
    assert ctx.increment("CNT") == 1
    assert ctx.increment("CNT") == 2
    assert ctx.increment("CNT") == 3


def test_increment_resolves_as_string_in_partial():
    ctx = VariableContext()
    ctx.increment("N")
    ctx.increment("N")
    assert ctx.resolve("count=${N}") == "count=2"


def test_increment_resolves_as_int_in_full_match():
    ctx = VariableContext()
    ctx.increment("N")
    result = ctx.resolve("${N}")
    assert result == 1
    assert isinstance(result, int)


def test_increment_custom_step():
    ctx = VariableContext()
    assert ctx.increment("CNT", 5) == 5
    assert ctx.increment("CNT", 5) == 10



def test_builtin_device_serial():
    ctx = VariableContext(device_serial="ABC123")
    assert ctx.resolve("${__DEVICE_SERIAL__}") == "ABC123"


def test_builtin_device_model():
    ctx = VariableContext(device_model="Pixel 7")
    assert ctx.resolve("device=${__DEVICE_MODEL__}") == "device=Pixel 7"


def test_builtin_now_is_iso_string():
    ctx = VariableContext()
    result = ctx.resolve("${__NOW__}")
    # ISO 8601: YYYY-MM-DDTHH:MM:SS...
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result)


def test_builtin_date_format():
    ctx = VariableContext()
    result = ctx.resolve("${__DATE__}")
    assert re.match(r"\d{4}-\d{2}-\d{2}$", result)


def test_builtin_time_format():
    ctx = VariableContext()
    result = ctx.resolve("${__TIME__}")
    assert re.match(r"\d{2}:\d{2}:\d{2}$", result)


def test_builtin_random_int():
    ctx = VariableContext()
    for _ in range(10):
        result = ctx.resolve("${__RANDOM_INT_1_100__}")
        assert isinstance(result, int)
        assert 1 <= result <= 100


def test_builtin_random_uuid():
    ctx = VariableContext()
    result = ctx.resolve("${__RANDOM_UUID__}")
    assert re.match(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        result,
    )


def test_builtin_step_index():
    ctx = VariableContext()
    assert ctx.resolve("${__STEP_INDEX__}", step_index=3) == 3


def test_builtin_not_overridden_by_env(monkeypatch):
    # __DEVICE_SERIAL__ shouldn't lookup os.environ
    monkeypatch.setenv("__DEVICE_SERIAL__", "env_value")
    ctx = VariableContext(device_serial="real_serial")
    # runtime/scenario/campaign are empty → built-in wins env for __*__ names
    assert ctx.resolve("${__DEVICE_SERIAL__}") == "real_serial"



def test_scenario_vars_from_dict():
    ctx = VariableContext(scenario_vars={"USERNAME": "user@test.com", "PASSWORD": "pass123"})
    step = {"type": "input_selector", "by": "resource-id", "value": "email", "text": "${USERNAME}"}
    resolved = ctx.resolve(step)
    assert resolved["text"] == "user@test.com"
    assert resolved["by"] == "resource-id"  # non-var fields unchanged


def test_campaign_vars_injection():
    ctx = VariableContext(campaign_vars={"BRAND": "TestApp"})
    assert ctx.resolve("${BRAND}") == "TestApp"


def test_full_step_resolution():
    ctx = VariableContext(scenario_vars={
        "SEL_TYPE": "resource-id",
        "SEL_VAL": "com.app:id/email",
        "INPUT": "hello@test.com",
    })
    step = {"type": "input_selector", "by": "${SEL_TYPE}", "value": "${SEL_VAL}", "text": "${INPUT}"}
    result = ctx.resolve(step)
    assert result == {
        "type": "input_selector",
        "by": "resource-id",
        "value": "com.app:id/email",
        "text": "hello@test.com",
    }


def test_normalize_device_vars_keeps_global_namespace():
    out = normalize_device_vars({"group_name": "device-group", "port": 5555, "empty": None})
    assert out == {"group_name": "device-group", "port": 5555, "empty": None}


def test_device_var_can_override_global_when_merged_into_scenario_vars():
    global_vars = {"group_name": "global-group", "save_collection": "global_collection"}
    device_vars = normalize_device_vars({"group_name": "device-group"})
    ctx = VariableContext(scenario_vars={**global_vars, **device_vars})
    assert ctx.resolve("${group_name}") == "device-group"
    assert ctx.resolve("${save_collection}") == "global_collection"
