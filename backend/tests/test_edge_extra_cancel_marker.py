"""Pause must reach the extract step as a cancellation, not as a failure.

Pressing pause sets the execution's pause flag, which trips the extract
activity's cancel_event and aborts the in-flight relay request. The activity
then decides what that abort meant:

    if edge_result.get("cancelled") and stop_reason.get("reason") == "paused":
        await _wait_until_unpaused()
        continue          # <- suspend, then redo this step
    break                 # <- the step failed

Only the boolean is read; the error *text* is just logged. The relay transport
returns both (`error: "cancelled"` and `cancelled: True`), but the failure
repack in _extra_data_via_relay_async kept only ok/error/route — so the flag was
lost, every pause looked like a failed extraction, the scenario failed, and the
run went to the DLQ. Pause ended the run instead of suspending it.

These tests pin the flag's survival across that repack.
"""
from __future__ import annotations

import pytest

from runtime.core.device_client import DeviceClient


class _FakeRelayManager:
    """Stands in for the relay transport, returning one canned reply."""

    def __init__(self, reply):
        self._reply = reply

    def relay_for_serial(self, _serial):
        return object()

    async def extra_data(self, **_kwargs):
        return self._reply


async def _call(reply, monkeypatch, *, context=None) -> dict:
    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.get_relay_manager",
        lambda: _FakeRelayManager(reply),
    )
    client = DeviceClient.__new__(DeviceClient)
    client._resolve_relay_serial = lambda: "SERIAL1"
    return await DeviceClient._extra_data_via_relay_async(
        client,
        strategy="posts",
        context=context or {},
        timeout=5.0,
        cancel_event=None,
    )


@pytest.mark.asyncio
async def test_cancellation_marker_survives_the_failure_repack(monkeypatch):
    out = await _call({"ok": False, "error": "cancelled", "cancelled": True}, monkeypatch)

    assert out["ok"] is False
    assert out["cancelled"] is True, (
        "without this the extract activity reads a paused step as a failed one"
    )


@pytest.mark.asyncio
async def test_ordinary_failures_are_not_marked_cancelled(monkeypatch):
    """A real error must stay a real error — pause must not swallow failures."""
    out = await _call({"ok": False, "error": "relay timeout (60s)"}, monkeypatch)

    assert out["ok"] is False
    assert "cancelled" not in out
    assert out["error"] == "relay timeout (60s)"


@pytest.mark.asyncio
async def test_error_text_alone_does_not_imply_cancellation(monkeypatch):
    """The flag is the contract, not the string.

    Matching on the message would misread any error whose text happens to
    mention cancellation as an operator pause, and silently retry forever.
    """
    out = await _call({"ok": False, "error": "cancelled by remote peer"}, monkeypatch)

    assert "cancelled" not in out


@pytest.mark.asyncio
async def test_success_path_is_unchanged(monkeypatch):
    out = await _call({"ok": True, "ingest": {"items": [1, 2]}, "route": "relay_u2"}, monkeypatch)

    assert out["ok"] is True
    assert out["ingest"] == {"items": [1, 2]}


@pytest.mark.asyncio
async def test_success_path_persists_relay_batch_with_trusted_relay_identity(monkeypatch):
    calls = []

    async def fake_persist_edge_batch(**kwargs):
        calls.append(kwargs)
        return {
            "attempted_count": 1,
            "inserted_count": 1,
            "duplicate_count": 0,
            "inserted_content_hashes": ["hash-1"],
            "batch_content_hashes": ["hash-1"],
            "db_ms": 7,
        }

    monkeypatch.setattr(
        "services.content.edge_ingest.persist_edge_batch",
        fake_persist_edge_batch,
    )
    batch = {
        "schema_version": 1,
        "kind": "content",
        "items": [{"body": "hello"}],
        "content_hashes": ["hash-1"],
        "captured_at": "2026-08-27T01:02:03+00:00",
    }
    out = await _call(
        {
            "ok": True,
            "_trusted_relay_id": "relay-server",
            "ingest": {"parsed_count": 1, "persist_batch": batch, "db_ms": 0},
        },
        monkeypatch,
        context={"collection": "posts", "return_items": True},
    )

    assert calls == [
        {
            "relay_id": "relay-server",
            "batch": batch,
            "trusted_context": {
                "collection": "posts",
                "return_items": True,
                "captured_at": "2026-08-27T01:02:03+00:00",
            },
        }
    ]
    assert out["ok"] is True
    assert out["ingest"]["inserted_count"] == 1
    assert out["ingest"]["items"] == [{"body": "hello"}]
    assert "persist_batch" not in out["ingest"]
