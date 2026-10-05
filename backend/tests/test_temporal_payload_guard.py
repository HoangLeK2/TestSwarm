"""Oversized values must never reach a Temporal payload.

Temporal warns at 256KB and hard-fails at 2MB. take_screenshot once inlined a
base64 JPEG (~665KB for a measured 499KB frame), so three such steps killed the
workflow. The guard runs in the activity interceptor so every activity is
covered, not just the one producer that was fixed.
"""
from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from typing import Any

from temporal.payload_guard import DEFAULT_MAX_VALUE_BYTES, strip_oversized_values
from temporal.shared import DeviceActionBatchResult, StepResult


def _blob(size: int = DEFAULT_MAX_VALUE_BYTES + 1) -> str:
    return "x" * size


def test_small_values_are_untouched():
    result = StepResult(index=0, step_type="tap", ok=True, details={"message": "fine"})
    assert strip_oversized_values(result) == []
    assert result.details["message"] == "fine"


def test_blob_nested_in_step_details_is_dropped_and_named():
    result = StepResult(
        index=3,
        step_type="take_screenshot",
        ok=True,
        details={"screenshot": _blob(), "duration_ms": 12},
    )
    dropped = strip_oversized_values(result)

    assert dropped == ["details.screenshot"]
    assert "dropped" in result.details["screenshot"]
    assert len(result.details["screenshot"]) < 200
    # Neighbouring fields survive — this trims, it does not discard the result.
    assert result.details["duration_ms"] == 12


def test_blob_inside_a_batch_result_list_is_dropped():
    batch = DeviceActionBatchResult(
        results=[
            {"index": 0, "ok": True, "message": "ok"},
            {"index": 1, "ok": True, "screenshot": _blob()},
        ],
        first_failure_index=-1,
    )
    dropped = strip_oversized_values(batch)

    assert dropped == ["results[1].screenshot"]
    assert batch.results[0]["message"] == "ok"


def test_bytes_are_measured_too():
    result = StepResult(
        index=0, step_type="x", ok=True, details={"raw": b"\x00" * (DEFAULT_MAX_VALUE_BYTES + 1)}
    )
    assert strip_oversized_values(result) == ["details.raw"]


def test_limit_is_on_encoded_size_not_character_count():
    # 3 bytes per character in UTF-8: under the limit by len(), over it by bytes.
    chars = (DEFAULT_MAX_VALUE_BYTES // 2)
    value = "一" * chars
    assert len(value) < DEFAULT_MAX_VALUE_BYTES
    result = StepResult(index=0, step_type="x", ok=True, details={"text": value})
    assert strip_oversized_values(result) == ["details.text"]


def test_cycles_do_not_hang():
    inner: dict[str, Any] = {"blob": _blob()}
    inner["self"] = inner
    result = StepResult(index=0, step_type="x", ok=True, details=inner)

    assert strip_oversized_values(result) == ["details.blob"]


@dataclass
class _Nested:
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Outer:
    child: _Nested = field(default_factory=_Nested)


def test_walks_into_nested_dataclasses():
    outer = _Outer(child=_Nested(payload={"blob": _blob()}))
    assert strip_oversized_values(outer) == ["child.payload.blob"]


def test_custom_limit():
    result = StepResult(index=0, step_type="x", ok=True, details={"m": "abcdef"})
    assert strip_oversized_values(result, limit=3) == ["details.m"]


@pytest.mark.asyncio
async def test_interceptor_trims_before_the_result_leaves_the_activity():
    """The guard must be wired into the interceptor, not just importable."""
    from temporal.trace import _TemporalTraceActivityInbound

    oversized = StepResult(
        index=0, step_type="take_screenshot", ok=True, details={"screenshot": _blob()}
    )

    class _Next:
        async def execute_activity(self, input):
            return oversized

    class _Input:
        args = ()
        fn = staticmethod(lambda: None)

    returned = await _TemporalTraceActivityInbound(_Next()).execute_activity(_Input())

    assert returned is oversized
    assert "dropped" in returned.details["screenshot"]


def test_runtime_context_is_never_trimmed():
    """Variables ride home in context and become the next step's inputs.

    Replacing one with a placeholder would let the scenario keep running on
    corrupted data — worse than hitting Temporal's limit with a clear error.
    """
    batch = DeviceActionBatchResult(
        results=[{"index": 0, "ok": True, "screenshot": _blob()}],
        first_failure_index=-1,
        context={"vars": {"BIG_LIST": _blob()}},
    )
    dropped = strip_oversized_values(batch)

    assert dropped == ["results[0].screenshot"]
    assert batch.context["vars"]["BIG_LIST"] == _blob()


def test_a_dict_key_named_context_is_also_protected():
    result = StepResult(
        index=0, step_type="x", ok=True,
        details={"context": {"vars": {"V": _blob()}}, "screenshot": _blob()},
    )
    dropped = strip_oversized_values(result)

    assert dropped == ["details.screenshot"]
    assert result.details["context"]["vars"]["V"] == _blob()
