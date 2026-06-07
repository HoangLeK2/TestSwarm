"""Tests for DLQ message resolution."""
from __future__ import annotations

from services.campaign.dlq_message import (
    coalesce_dlq_text,
    failure_from_step_results,
    resolve_dlq_message,
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
