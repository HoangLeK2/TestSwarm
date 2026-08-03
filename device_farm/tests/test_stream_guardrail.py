from __future__ import annotations

import logging

import pytest

from web import server


def test_stream_guardrail_status_ok_for_isolated_media_ws() -> None:
    status = server._stream_guardrail_status(
        stream_telemetry={
            "ws_dropped": 0,
            "ws_send_wait_p95_ms": 1.0,
        },
        websocket_streams={
            "max_media_streams_per_connection": 1,
            "shared_media_ws_connections": 0,
            "top_dropped_serials": [],
        },
    )

    assert status["ok"] is True
    assert status["violations"] == []
    assert status["observed"]["max_media_streams_per_connection"] == 1


def test_stream_guardrail_status_flags_shared_ws_and_backpressure() -> None:
    status = server._stream_guardrail_status(
        stream_telemetry={
            "ws_dropped": 12,
            "ws_send_wait_p95_ms": 9.0,
        },
        websocket_streams={
            "max_media_streams_per_connection": 40,
            "shared_media_ws_connections": 1,
            "top_dropped_serials": [{"serial": "SN001", "count": 12}],
        },
    )

    assert status["ok"] is False
    assert status["violations"] == [
        "shared_media_ws",
        "ws_drops",
        "ws_send_wait_p95",
    ]
    assert status["observed"]["top_dropped_serials"] == [
        {"serial": "SN001", "count": 12}
    ]


def test_stream_guardrail_warning_is_throttled(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server, "STREAM_GUARDRAIL_WARN_INTERVAL_S", 15.0)
    monkeypatch.setattr(server, "_last_stream_guardrail_warning_at", 0.0)
    status = {
        "ok": False,
        "violations": ["shared_media_ws"],
        "observed": {
            "max_media_streams_per_connection": 40,
            "shared_media_ws_connections": 1,
            "ws_dropped": 10,
            "ws_send_wait_p95_ms": 8.0,
            "top_dropped_serials": [{"serial": "SN001", "count": 10}],
        },
    }

    with caplog.at_level(logging.WARNING, logger=server.__name__):
        server._warn_stream_guardrail_if_needed(
            stream_guardrail=status,
            now=100.0,
        )
        server._warn_stream_guardrail_if_needed(
            stream_guardrail=status,
            now=101.0,
        )
        server._warn_stream_guardrail_if_needed(
            stream_guardrail=status,
            now=116.0,
        )

    warnings = [
        record.getMessage()
        for record in caplog.records
        if "stream guardrail violation" in record.getMessage()
    ]
    assert len(warnings) == 2
    assert "max_streams_per_connection=40" in warnings[0]


def test_stream_guardrail_warning_skips_ok_status(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=server.__name__):
        server._warn_stream_guardrail_if_needed(
            stream_guardrail={"ok": True},
            now=200.0,
        )

    assert caplog.records == []
