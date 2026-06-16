"""Tests for temporal/trace.py structured logging helpers."""
from __future__ import annotations

from dataclasses import dataclass

from temporal.shared import ElementCheckInput
from temporal.trace import summarize_activity_input


@dataclass
class _BatchInput:
    device_serial: str
    execution_id: str
    steps: list[dict]


def test_summarize_activity_input_element_check():
    summary = summarize_activity_input(
        (
            ElementCheckInput(
                device_serial="10AE7S00HD002JK",
                by="text",
                value="OK",
                timeout=5.0,
                execution_id="exec-1",
            ),
        )
    )
    assert summary["device_serial"] == "10AE7S00HD002JK"
    assert summary["execution_id"] == "exec-1"
    assert summary["by"] == "text"
    assert summary["value"] == "OK"
    assert summary["timeout"] == 5.0


def test_summarize_activity_input_batch():
    summary = summarize_activity_input(
        (
            _BatchInput(
                device_serial="dev-1",
                execution_id="exec-2",
                steps=[{"type": "tap"}, {"type": "scroll"}],
            ),
        )
    )
    assert summary["batch_size"] == 2
    assert summary["device_serial"] == "dev-1"
