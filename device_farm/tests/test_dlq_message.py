"""Tests for DLQ message resolution."""
from __future__ import annotations

from services.campaign.dlq_message import (
    coalesce_dlq_text,
    failure_from_step_results,
    resolve_dlq_message,
    sanitize_operator_dlq_text,
)


def test_coalesce_dlq_text_never_empty():
    assert "recorded error message" in coalesce_dlq_text(None, "", None)


def test_failure_from_step_results_uses_workflow_message():
    step_id, reason = failure_from_step_results([], "loop: iteration 3 failed — timeout")
    assert step_id is None
    assert reason == "loop: iteration 3 failed — timeout"


def test_failure_from_step_results_prefers_failed_step_message():
    step_id, reason = failure_from_step_results(
        [{"ok": False, "index": 2, "message": "selector not found"}],
        None,
    )
    assert step_id == "2"
    assert reason == "selector not found"


def test_resolve_dlq_message_adds_hints_when_empty():
    msg = resolve_dlq_message(
        error=None,
        failure_reason=None,
        failed_step_id="loop-1",
        execution_id="exec-1",
    )
    assert "failed_step_id=loop-1" in msg
    assert "execution_id=exec-1" in msg


def test_sanitize_operator_dlq_text_collapses_u2_stack_trace():
    raw = (
        "loop: iteration 1 failed — edge extra_data failed: [server] INFO: "
        "[UiAutomator2Server] Starting Server java.lang.IllegalStateException: "
        "UiAutomationService already registered!"
    )
    assert sanitize_operator_dlq_text(raw) == (
        "loop: iteration 1 failed — edge extra_data failed: u2_transient_error"
    )


def test_sanitize_operator_dlq_text_keeps_actionable_extra_data_errors():
    raw = "edge extra_data failed: FK violation DETAIL: Key (campaign_id)=(abc) is not present"
    assert sanitize_operator_dlq_text(raw) == raw


def test_resolve_dlq_message_sanitizes_u2_extra_data_for_display():
    msg = resolve_dlq_message(
        error=None,
        failure_reason=(
            "edge extra_data failed: java.lang.IllegalStateException: "
            "UiAutomation not connected"
        ),
    )
    assert msg == "edge extra_data failed: u2_transient_error"


def test_sanitize_operator_dlq_text_collapses_direct_json_rpc_502():
    raw = (
        "run_scenario: sub-scenario 'abc' failed — "
        "loop: iteration 2 failed — JSON-RPC HTTP 502"
    )
    assert sanitize_operator_dlq_text(raw) == (
        "run_scenario: sub-scenario 'abc' failed — "
        "loop: iteration 2 failed — u2_transient_error"
    )


def test_failure_from_step_results_preserves_classified_metadata_message():
    step_id, reason = failure_from_step_results(
        [
            {
                "ok": False,
                "index": 4,
                "failure_class": "device_lost",
                "reason_code": "device_lost",
                "message": "device offline",
            }
        ],
        None,
    )

    assert step_id == "4"
    assert reason == "device offline"
