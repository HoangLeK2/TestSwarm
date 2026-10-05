"""Node-contract checks, held in parity across the two validation stacks.

There are two parallel validators — org scenarios and campaign scenarios — with
the same checks written twice. Any contract rule that lands in one and not the
other means the editor's answer depends on which endpoint the save went through.
These tests run each rule through both.
"""
from __future__ import annotations

import pytest

from common.scenario_schema import unknown_step_fields
from services.org_scenario_validation import checks as org_checks
from services.org_scenario_validation.step_index import OrgStepIndex
from services.scenario_validation import checks as camp_checks
from services.scenario_validation import codes as C
from services.scenario_validation.models import ValidationResult
from services.scenario_validation.step_index import StepIndex


both_stacks = pytest.mark.parametrize(
    ("checks_mod", "index_cls"),
    [(org_checks, OrgStepIndex), (camp_checks, StepIndex)],
    ids=["org", "campaign"],
)


def _run(check_name, checks_mod, index_cls, steps: list[dict]) -> ValidationResult:
    result = ValidationResult()
    getattr(checks_mod, check_name)(index_cls.build(steps), result)
    return result


# ── unknown_step_fields ────────────────────────────────────────────────────


def test_unknown_step_fields_flags_a_typo():
    step = {"type": "tap", "timeout": 4, "wait_after": True}

    assert unknown_step_fields(step) == ["wait_after"]


def test_unknown_step_fields_accepts_the_step_envelope():
    step = {
        "type": "tap",
        "id": "n1",
        "order": "a0",
        "title": "Tap login",
        "description": "",
        "config": {},
        "error_policy": "stop",
        "retry": None,
        "pre_capture": False,
        "post_capture": False,
    }

    assert unknown_step_fields(step) == []


def test_unknown_step_fields_stays_quiet_on_dotted_dsl_types():
    """No STEP_SCHEMA entry means no contract to check — not "everything is wrong"."""
    assert unknown_step_fields({"type": "interaction.tap", "anything": 1}) == []
    assert unknown_step_fields({"type": "", "anything": 1}) == []
    assert unknown_step_fields("not a dict") == []


def test_unknown_step_fields_accepts_newly_declared_runtime_fields():
    """Fields the executor reads but the schema used to omit (2.2)."""
    assert unknown_step_fields(
        {"type": "loop", "steps": [], "stall_after": 3, "idle_delay_seconds": 2}
    ) == []
    assert unknown_step_fields(
        {"type": "extract_text_ocr", "save_as": "x", "confidence_threshold": 0.5}
    ) == []
    assert unknown_step_fields(
        {"type": "launch_app", "package": "com.x", "package_fallbacks": [], "adb_fallback": True}
    ) == []


@both_stacks
def test_check_step_fields_warns_and_never_errors(checks_mod, index_cls):
    result = _run(
        "check_step_fields",
        checks_mod,
        index_cls,
        [{"id": "s1", "type": "tap", "wait_after": True}],
    )

    assert result.errors == []
    assert [i.code for i in result.warnings] == [C.UNKNOWN_STEP_FIELD]
    assert "wait_after" in result.warnings[0].location
    assert result.status == "valid"


@both_stacks
def test_check_step_fields_is_silent_on_a_clean_scenario(checks_mod, index_cls):
    result = _run(
        "check_step_fields",
        checks_mod,
        index_cls,
        [
            {"id": "s1", "type": "launch_app", "package": "com.x"},
            {"id": "s2", "type": "wait_element", "by": "text", "value": "Home"},
        ],
    )

    assert result.all_issues() == []


# ── content_interaction completion_verify ──────────────────────────────────


@both_stacks
@pytest.mark.parametrize("action", ["comment", "share"])
def test_comment_and_share_require_completion_verify(checks_mod, index_cls, action):
    result = _run(
        "check_content_interaction_verify",
        checks_mod,
        index_cls,
        [{"id": "s1", "type": "content_interaction", "action": action}],
    )

    assert [i.code for i in result.errors] == [C.COMPLETION_VERIFY_REQUIRED]
    assert result.status == "invalid"


@both_stacks
def test_completion_verify_satisfies_the_rule(checks_mod, index_cls):
    result = _run(
        "check_content_interaction_verify",
        checks_mod,
        index_cls,
        [
            {
                "id": "s1",
                "type": "content_interaction",
                "action": "comment",
                "completion_verify": {"by": "text", "value": "Đã gửi"},
            }
        ],
    )

    assert result.all_issues() == []


@both_stacks
def test_actions_with_readable_state_are_left_alone(checks_mod, index_cls):
    """like/follow flip a visible toggle, so already-applied dedupe covers them."""
    result = _run(
        "check_content_interaction_verify",
        checks_mod,
        index_cls,
        [
            {"id": "s1", "type": "content_interaction", "action": "like"},
            {"id": "s2", "type": "content_interaction", "action": "follow"},
        ],
    )

    assert result.all_issues() == []


def test_verify_required_actions_match_the_runtime_set():
    """If social_actions grows a third stateless action, this must follow."""
    from tasks.scenario.steps.social_actions import _GLOBAL_VERIFY_CONTENT_ACTIONS

    assert org_checks._VERIFY_REQUIRED_ACTIONS == set(_GLOBAL_VERIFY_CONTENT_ACTIONS)
    assert camp_checks._VERIFY_REQUIRED_ACTIONS == set(_GLOBAL_VERIFY_CONTENT_ACTIONS)
