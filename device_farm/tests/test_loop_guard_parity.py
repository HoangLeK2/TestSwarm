"""Guard: the two loop implementations must not drift apart.

There are two. ``tasks/scenario/steps/control_flow.py`` drives directly-run and
nested scenarios; ``temporal/workflows.py`` drives campaigns. They are separate
code paths for the same DSL step, and nothing connected them.

That cost a real run. ``stall_after`` and ``idle_delay_seconds`` were added to
the scenario executor, verified by unit tests, deployed — and then a campaign
span 204 iterations in 8.5 minutes on a screen it could not act on, because
campaigns never reach that file. The tests were green and the feature was
absent from the path that actually runs production work.

So the parity is asserted here rather than remembered.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_EXECUTOR_LOOP = _ROOT / "tasks" / "scenario" / "steps" / "control_flow.py"
_EXECUTOR_COMPOSITION = _ROOT / "tasks" / "scenario" / "steps" / "composition.py"
_WORKFLOW_LOOP = _ROOT / "temporal" / "workflows.py"

# Step keys each control-flow node reads. Both implementations must honour every
# one, or a scenario behaves differently depending on how it was started — the
# hardest kind of bug to see, because each path looks correct on its own.
#
# `loop` was the only node covered when this guard was written; the other seven
# share the same two-implementation shape and the same failure mode.
_STEP_KEYS_BY_NODE: dict[str, tuple[str, ...]] = {
    "loop": (
        "count",
        "count_min",
        "count_max",
        "delay_between_min",
        "delay_between_max",
        "while",
        "max_iterations",
        "loop_var",
        "steps",
        "stall_after",
        "idle_delay_seconds",
    ),
    "if": ("condition", "then", "else"),
    "repeat": ("count", "delay_between", "steps"),
    "repeat_until": ("condition", "max_iterations", "steps"),
    # `by`/`value` are read through resolve_step_selector_fields in the executor
    # and inline in the workflow, so they are not comparable as literals here.
    "if_element": ("timeout", "then", "else"),
    "if_variable": (
        "name",
        "then",
        "else",
        "equals",
        "not_equals",
        "contains",
        "greater_than",
    ),
    "random_pick": ("branches", "weight", "steps"),
    "run_scenario": (
        "scenario_id",
        "scenario_name",
        "variables",
        "steps",
        "by_id",
        "by_campaign_name",
        "by_template_name",
    ),
}

_CASES = [
    (node, key) for node, keys in _STEP_KEYS_BY_NODE.items() for key in keys
]

_PATHS_BY_NODE = {
    "run_scenario": (_EXECUTOR_COMPOSITION, _WORKFLOW_LOOP),
}

# Subscripts only count when the container is the step dict itself. Any
# `ast.Constant` used to count, which meant a key mentioned in a comment or in
# an unrelated `result["..."]` write satisfied the guard.
_STEP_CONTAINERS = {"step", "raw_step"}


def _read_step_keys(path: Path) -> set[str]:
    """String literals used to read a key: `.get("k")` or `step["k"]`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in _STEP_CONTAINERS
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


@pytest.mark.parametrize(("node", "key"), _CASES, ids=[f"{n}:{k}" for n, k in _CASES])
def test_both_control_flow_implementations_read_the_same_step_keys(
    node: str, key: str
) -> None:
    missing = [
        path.relative_to(_ROOT).as_posix()
        for path in _PATHS_BY_NODE.get(node, (_EXECUTOR_LOOP, _WORKFLOW_LOOP))
        if key not in _read_step_keys(path)
    ]
    assert not missing, (
        f"{node}: the step key {key!r} is handled in only one of the two "
        f"control-flow implementations — missing from {missing}. A scenario "
        f"would then behave differently depending on whether it was run "
        f"directly or as a campaign."
    )


def test_both_implementations_agree_on_what_counts_as_progress() -> None:
    """The distinction that decides whether a paced campaign survives.

    ``rate_limited`` must reset the stall streak in both, or a correctly
    throttled campaign fails exactly when the safety limit starts working.
    """
    from tasks.scenario.steps.control_flow import _DELIBERATE_NO_ACTION_OUTCOMES as a
    from temporal.workflows import _DELIBERATE_NO_ACTION_OUTCOMES as b

    assert a == b, "the two loops disagree about which no-ops are deliberate"
    assert "rate_limited" in a


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (None, None, (None, None)),
        ("", "", (None, None)),
        (10, None, None),      # half a range is a typo, not "from 10 upward"
        (None, 50, None),
        ("x", "50", None),
        (50, 10, None),        # reversed bounds
        (10, 50, ((10, 50), None)),
        ("10", "50", ((10, 50), None)),
    ],
)
def test_both_implementations_read_random_ranges_the_same_way(
    low, high, expected
) -> None:
    """The twin helpers must agree, or a range means one thing per run path."""
    from tasks.scenario.steps.control_flow import _resolve_random_range
    from temporal.workflows import _loop_random_range

    executor = _resolve_random_range(low, high, int)
    campaign = _loop_random_range(low, high, int)

    assert executor[0] == campaign[0]
    assert bool(executor[1]) == bool(campaign[1])
    if expected is None:
        assert executor[0] is None and executor[1]
    else:
        assert executor == expected


def test_both_implementations_walk_nested_branches() -> None:
    """``connection_request`` sits two ``if_variable`` levels down.

    A shallow read finds only the wrappers and calls a working iteration idle,
    so both walkers are checked against the shape that actually occurs.
    """
    from tasks.scenario.steps.control_flow import _performed_action
    from temporal.workflows import _loop_performed_action

    buried = {
        "type": "if_variable",
        "sub_result": {
            "step_results": [
                {
                    "type": "if_variable",
                    "sub_result": {
                        "step_results": [
                            {"type": "connection_request", "action_performed": True}
                        ]
                    },
                }
            ]
        },
    }

    assert _loop_performed_action([buried]) is True
    assert _performed_action({"step_results": [buried]}) is True
