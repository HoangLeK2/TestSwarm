"""Every execution_step row must say which phone ran it.

The column and the CRUD have accepted device_id all along; only the payload
builder never set it, so the column measured 0 of 616 rows — "which device ran
this step" was unanswerable, and the account-action device backfill, which
joins through execution_steps, recovered nothing.
"""
from __future__ import annotations

from services.execution.step_store import (
    build_execution_step_payload,
    build_execution_step_payload_from_result,
)


def _result(index: int = 0) -> dict:
    return {"index": index, "type": "tap", "ok": True, "message": "ok"}


def test_payload_carries_device_id_when_given():
    payload = build_execution_step_payload(
        "exec-1", {"type": "tap"}, _result(), device_id="dev-uuid"
    )
    assert payload["device_id"] == "dev-uuid"


def test_payload_omits_the_key_when_the_device_is_unknown():
    """Absent is not the same as NULL: leave the column to its own default."""
    payload = build_execution_step_payload("exec-1", {"type": "tap"}, _result())
    assert "device_id" not in payload


def test_finalize_shaped_builder_forwards_device_id():
    payload = build_execution_step_payload_from_result(
        "exec-1", _result(2), device_id="dev-uuid"
    )
    assert payload["device_id"] == "dev-uuid"
    assert payload["step_index"] == 2


def test_payload_is_accepted_by_the_crud_signature():
    """Guards the seam that was broken: builder output feeds upsert as kwargs."""
    import inspect

    from db.crud.execution_steps import upsert_execution_step

    accepted = set(inspect.signature(upsert_execution_step).parameters)
    payload = build_execution_step_payload(
        "exec-1", {"type": "tap"}, _result(), device_id="dev-uuid"
    )
    unexpected = set(payload) - accepted
    assert not unexpected, f"upsert_execution_step would reject: {unexpected}"
