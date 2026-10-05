from __future__ import annotations

import pytest

from services.campaign.execution_runtime import build_sequence_steps


def test_build_sequence_steps_expands_repeat_count_in_order():
    steps = build_sequence_steps(
        [
            {"scenario_id": "A"},
            {"scenario_id": "B", "repeat_count": 2},
            {"scenario_id": "C"},
        ],
        device_index=4,
        effective_vars={"kw": "device"},
        account_vars={"account.username": "u1"},
        campaign_vars={"kw": "campaign"},
        scenario_device_vars={"B": {"kw": "b-device"}},
    )

    assert [step["scenario_id"] for step in steps] == ["A", "B", "B", "C"]
    assert [step["scenario_sequence_index"] for step in steps] == [0, 1, 2, 3]
    assert [step["repeat_index"] for step in steps] == [0, 0, 1, 0]
    assert [step["repeat_count"] for step in steps] == [1, 2, 2, 1]
    assert steps[1]["variables"]["kw"] == "b-device"
    assert steps[2]["variables"]["kw"] == "b-device"
    assert steps[2]["variables"]["SCENARIO_INDEX"] == "2"
    assert steps[2]["variables"]["SCENARIO_REF_INDEX"] == "1"
    assert steps[2]["variables"]["SCENARIO_REPEAT_INDEX"] == "1"
    assert steps[2]["variables"]["SCENARIO_REPEAT_COUNT"] == "2"


@pytest.mark.parametrize("repeat_count", [0, -1, 21, "bad"])
def test_build_sequence_steps_rejects_invalid_repeat_count(repeat_count):
    with pytest.raises(ValueError):
        build_sequence_steps(
            [{"scenario_id": "A", "repeat_count": repeat_count}],
            device_index=0,
            effective_vars={},
            account_vars={},
        )
