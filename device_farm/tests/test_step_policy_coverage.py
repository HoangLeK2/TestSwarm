"""Every registered node must declare a side-effect class explicitly.

A node with no declaration used to fall through to the `device_effect` default
silently. That default is safe for retries but wrong for stall thresholds, and
nothing told the author their node had been classified by accident. This guard
fails the build instead.

Same family as test_fb_label_guard.py: if it blocks you, add the node to the
right set in step_activity_policy.py — do not widen the guard.
"""
from __future__ import annotations

from tasks.scenario.steps import _STEP_HANDLERS
from temporal.step_activity_policy import (
    _DEVICE_EFFECT_STEP_TYPES,
    _IO_EFFECT_STEP_TYPES,
    _READ_STEP_TYPES,
    _SOCIAL_EFFECT_STEP_TYPES,
    _WORKFLOW_HANDLED_STEP_TYPES,
    step_side_effect_class,
)

_EXPLICIT = (
    _READ_STEP_TYPES
    | _IO_EFFECT_STEP_TYPES
    | _DEVICE_EFFECT_STEP_TYPES
    | _SOCIAL_EFFECT_STEP_TYPES
    | _WORKFLOW_HANDLED_STEP_TYPES
)


def test_every_registered_step_has_explicit_side_effect_class():
    missing = sorted(
        t for t in _STEP_HANDLERS if t not in _EXPLICIT and not t.startswith("social_")
    )
    assert not missing, f"node chưa khai side-effect class: {missing}"


def test_step_type_is_declared_in_exactly_one_class():
    # `extract`/`save_extraction` legitimately sit in io_effect only; anything
    # in two effect classes means the lookup order is deciding, not the author.
    effect_sets = {
        "read": _READ_STEP_TYPES,
        "io_effect": _IO_EFFECT_STEP_TYPES,
        "device_effect": _DEVICE_EFFECT_STEP_TYPES,
        "social_effect": _SOCIAL_EFFECT_STEP_TYPES,
    }
    overlaps = {
        step_type: sorted(name for name, s in effect_sets.items() if step_type in s)
        for step_type in _STEP_HANDLERS
    }
    duplicated = {k: v for k, v in overlaps.items() if len(v) > 1}
    assert not duplicated, f"node khai nhiều side-effect class: {duplicated}"


def test_db_lease_nodes_are_not_social_effect():
    # Regression: the old substring matcher classified this as social_effect
    # because the type name contains "connect".
    assert step_side_effect_class({"type": "lease_connection_candidate"}) == "io_effect"


def test_social_action_nodes_are_social_effect():
    for step_type in ("content_interaction", "connection_request", "community_membership"):
        assert step_side_effect_class({"type": step_type}) == "social_effect"
