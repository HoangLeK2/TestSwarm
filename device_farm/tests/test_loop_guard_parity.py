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
_WORKFLOW_LOOP = _ROOT / "temporal" / "workflows.py"

# Step keys the loop reads. Both implementations must honour every one, or a
# scenario behaves differently depending on how it was started — the hardest
# kind of bug to see, because each path looks correct on its own.
_LOOP_STEP_KEYS = (
    "count",
    "while",
    "max_iterations",
    "loop_var",
    "steps",
    "stall_after",
    "idle_delay_seconds",
)


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


@pytest.mark.parametrize("key", _LOOP_STEP_KEYS)
def test_both_loop_implementations_read_the_same_step_keys(key: str) -> None:
    missing = [
        path.relative_to(_ROOT).as_posix()
        for path in (_EXECUTOR_LOOP, _WORKFLOW_LOOP)
        if key not in _string_constants(path)
    ]
    assert not missing, (
        f"the loop step key {key!r} is handled in only one of the two loop "
        f"implementations — missing from {missing}. A scenario would then behave "
        f"differently depending on whether it was run directly or as a campaign."
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
