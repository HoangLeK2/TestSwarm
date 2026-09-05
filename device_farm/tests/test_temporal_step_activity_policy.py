from __future__ import annotations

from datetime import timedelta

from temporal.step_activity_policy import (
    batch_activity_id,
    build_batch_activity_policy,
    build_step_activity_policy,
    step_activity_id,
    step_side_effect_class,
    workflow_activity_id,
)


def test_step_activity_id_is_deterministic_and_attempt_scoped():
    step = {"id": "login.tap/button", "type": "tap_selector"}

    assert step_activity_id(
        execution_id="execution-1",
        step=step,
        step_index=3,
        attempt=1,
    ) == step_activity_id(
        execution_id="execution-1",
        step=step,
        step_index=3,
        attempt=1,
    )
    assert step_activity_id(
        execution_id="execution-1",
        step=step,
        step_index=3,
        attempt=2,
    ).endswith(":attempt:2")


def test_side_effect_steps_do_not_retry_inside_temporal_activity():
    policy = build_step_activity_policy(
        execution_id="execution-1",
        step={"id": "send", "type": "social_send_message"},
        step_index=4,
        attempt=1,
    )

    assert policy.side_effect_class == "social_effect"
    assert policy.retry_policy.maximum_attempts == 1
    assert policy.activity_id == "step:execution-1:send:social_send_message:attempt:1"


def test_read_only_steps_get_bounded_activity_retry_and_timeout():
    policy = build_step_activity_policy(
        execution_id="execution-1",
        step={"id": "wait-ready", "type": "wait_element", "timeout": 75},
        step_index=2,
        attempt=1,
    )

    assert step_side_effect_class({"type": "wait_element"}) == "read"
    assert policy.retry_policy.maximum_attempts == 2
    assert policy.start_to_close_timeout == timedelta(seconds=85)
    assert policy.heartbeat_timeout == timedelta(seconds=30)


def test_unknown_steps_are_conservative_device_effects():
    policy = build_step_activity_policy(
        execution_id="execution-1",
        step={"type": "future_platform_step"},
        step_index=9,
    )

    assert policy.side_effect_class == "device_effect"
    assert policy.retry_policy.maximum_attempts == 1
    assert policy.heartbeat_timeout == timedelta(seconds=60)


def test_io_effect_steps_keep_wide_heartbeat_and_no_auto_retry():
    policy = build_step_activity_policy(
        execution_id="execution-1",
        step={"id": "save", "type": "save_extraction"},
        step_index=5,
        default_start_to_close_timeout=timedelta(seconds=120),
    )

    assert policy.side_effect_class == "io_effect"
    assert policy.retry_policy.maximum_attempts == 1
    assert policy.heartbeat_timeout == timedelta(seconds=60)


def test_batch_policy_keeps_single_attempt_and_step_activity_ids():
    steps = [
        {"id": "tap-a", "type": "tap_position"},
        {"id": "input-b", "type": "input_text"},
    ]
    policy = build_batch_activity_policy(
        execution_id="execution-1",
        steps=steps,
        step_indices=[10, 11],
        start_to_close_timeout=timedelta(seconds=240),
    )

    assert policy.activity_id == batch_activity_id(
        execution_id="execution-1",
        steps=steps,
        step_indices=[10, 11],
    )
    assert policy.retry_policy.maximum_attempts == 1
    assert policy.start_to_close_timeout == timedelta(seconds=240)
    assert policy.step_activity_ids == [
        "step:execution-1:tap-a:tap_position:attempt:1",
        "step:execution-1:input-b:input_text:attempt:1",
    ]


def test_workflow_activity_id_is_stable_for_control_activities():
    step = {"id": "branch-check", "type": "if_element"}

    assert workflow_activity_id(
        execution_id="execution-1",
        activity_name="check_element_exists",
        step=step,
        step_index=8,
        qualifier="then",
    ) == (
        "activity:execution-1:check_element_exists:8:branch-check:then"
    )
