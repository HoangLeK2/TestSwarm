"""Guards for the account-activity semantic layer.

The coverage test is the point of this file: a new step type that touches the
device but has no semantic name silently disappears from the account timeline,
and nothing else in the build notices.
"""
from __future__ import annotations

from services.execution.action_semantics import describe, known_step_types
from tasks.scenario.steps import _STEP_HANDLERS  # noqa: F401 — triggers registration

# Step types that deliberately produce no account-activity line, with the reason.
# Adding a row here is the escape hatch; widening the semantics table is not.
TECHNICAL_STEPS = {
    # control flow — execution structure, not something the account did
    "loop": "control flow",
    "repeat": "control flow",
    "repeat_until": "control flow",
    "if": "control flow",
    "if_element": "control flow",
    "if_variable": "control flow",
    "break_if": "control flow",
    "random_pick": "control flow",
    "run_scenario": "control flow",
    # reads — observe the screen, change nothing
    "extract": "read-only",
    "extract_screen_data": "read-only",
    "extract_text_ai": "read-only",
    "extract_text_hierarchy": "read-only",
    "extract_text_ocr": "read-only",
    "assert_element": "read-only",
    "assert_app_state": "read-only",
    "verify_screen": "read-only",
    "take_screenshot": "read-only",
    "wait": "read-only",
    "wait_element": "read-only",
    "wait_stable": "read-only",
    "dismiss_popup": "read-only",
    # bookkeeping — never reaches the UI
    "set_var": "runtime variable",
    "set_variable": "runtime variable",
    "save_extraction": "persistence",
    "use_source_pool": "persistence",
    "lease_source_target": "persistence",
    "lease_connection_candidate": "persistence",
    "push_file": "device file transfer",
    "pull_file": "device file transfer",
    "adb_shell": "device diagnostics",
}


def _production_step_types() -> set[str]:
    """Step types registered by the shipped handler modules.

    ``_STEP_HANDLERS`` is a process-global registry, and other test modules
    register stubs into it. Filtering by defining module keeps this guard about
    the product rather than about whatever ran first.
    """
    return {
        step_type
        for step_type, handler in _STEP_HANDLERS.items()
        if getattr(handler, "__module__", "").startswith("tasks.scenario.steps")
    }


def test_every_registered_step_type_is_classified():
    covered = known_step_types() | set(TECHNICAL_STEPS)
    unclassified = sorted(_production_step_types() - covered)
    assert not unclassified, (
        "These step types have no semantic action and are not declared "
        f"technical, so they will not appear in any account timeline: {unclassified}. "
        "Add them to services/execution/action_semantics.py, or to "
        "TECHNICAL_STEPS here with a reason."
    )


def test_text_entry_label_never_leaks_the_typed_text():
    secret = "my private comment body"
    step = {"type": "input_text", "text": secret}
    action, sentence = describe(step, {"typed_text": secret})
    assert action == "ui.input"
    assert secret not in sentence
    assert str(len(secret)) in sentence


def test_discriminator_picks_the_precise_operation():
    assert describe({"type": "content_interaction", "action": "like"})[0] == "post.like"
    assert describe({"type": "content_interaction", "action": "share"})[0] == "post.share"
    # No action field falls back to the step type's generic name.
    assert describe({"type": "content_interaction"})[0] == "post.interact"
    assert describe({"type": "key", "key": "back"})[0] == "navigation.back"


def test_node_declared_semantic_action_wins():
    # A tap_selector cannot know it opens comments; the node author can say so.
    step = {"type": "tap_selector", "semantic_action": "comment.section_open", "value": "Comment"}
    action, sentence = describe(step, {})
    assert action == "comment.section_open"
    assert "Comment" in sentence


def test_technical_step_produces_no_activity_line():
    assert describe({"type": "extract", "save_as": "x"}) is None
    assert describe({"type": "loop", "steps": []}) is None


def test_ledger_actions_are_domain_level_only():
    from services.execution.action_semantics import LEDGER_ACTIONS

    ui = sorted(a for a in LEDGER_ACTIONS if a.startswith("ui."))
    assert not ui, f"UI operations must not write a ledger row: {ui}"


def test_ledger_target_refuses_an_unnameable_target():
    from services.execution.action_semantics import ledger_target

    # No id, no label, no selector -> no row. stable_action_key hashes the
    # target, so an empty one would merge every occurrence into one record.
    assert ledger_target("post.open", {"type": "tap_selector"}, {}) is None
    named = ledger_target("post.open", {"type": "tap_selector"}, {"external_entity_id": "p1"})
    assert named["target_id"] == "p1"
    assert named["target_type"] == "post"


def test_entity_target_is_never_taken_from_the_selector():
    from services.execution.action_semantics import ledger_target

    # A failed connection.request knows which button it looked for but not which
    # person it was for. No row beats a row naming the button as the person.
    step = {"type": "tap_selector", "value": "Add Friend", "semantic_action": "connection.request"}
    assert ledger_target("connection.request", step, {}) is None
    # Once the screen names the person, the row is filed against them.
    identified = ledger_target("connection.request", step, {"display_name": "Tran Thi B"})
    assert identified["target_id"] == "Tran Thi B"
    # A filter has no identity beyond its own wording, so the selector stands.
    assert ledger_target("filter.apply", {"type": "tap_selector", "value": "Most relevant"}, {})[
        "target_id"
    ] == "Most relevant"
