from __future__ import annotations

from services.execution.trace_context import (
    TRACE_CONTEXT_KEY,
    build_step_trace_context,
    push_step_path,
)


def test_push_step_path_appends_without_mutating_parent_context():
    parent = {
        TRACE_CONTEXT_KEY: {
            "scenario_id": "scenario-1",
            "step_path": "outer#2",
            "loop_iter": 2,
        },
        "vars": {"x": "1"},
    }

    child = push_step_path(
        parent,
        step_id="branch_gate",
        branch="then",
        step_type="if_variable",
        step_index=3,
    )

    assert parent[TRACE_CONTEXT_KEY]["step_path"] == "outer#2"
    assert child[TRACE_CONTEXT_KEY]["step_path"] == "outer#2/branch_gate.then"
    assert child[TRACE_CONTEXT_KEY]["branch"] == "then"
    assert child["vars"] == {"x": "1"}


def test_build_step_trace_context_exposes_loop_branch_fields():
    runtime_context = push_step_path(
        {
            TRACE_CONTEXT_KEY: {
                "scenario_id": "scenario-1",
                "device_serial": "phone-1",
            }
        },
        step_id="cycle",
        loop_iter=7,
        step_type="loop",
        step_index=1,
    )
    runtime_context = push_step_path(
        runtime_context,
        step_id="gate",
        branch="else",
        step_type="if_variable",
        step_index=2,
    )

    trace = build_step_trace_context(
        step={"id": "tap_name", "type": "tap"},
        step_index=3,
        depth=2,
        runtime_context=runtime_context,
    )

    assert trace["step_path"] == "cycle#7/gate.else"
    assert trace["loop_id"] == "cycle"
    assert trace["loop_iter"] == 7
    assert trace["branch"] == "else"
    assert trace["step_id"] == "tap_name"
