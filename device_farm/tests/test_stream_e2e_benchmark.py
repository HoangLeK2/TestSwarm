from __future__ import annotations

import pytest

from scripts.benchmark_stream_e2e import _run
from tests.perf_assertions import perf_budget


@pytest.mark.asyncio
async def test_stream_e2e_isolated_media_path_keeps_fast_phones_under_budget() -> None:
    result = await _run(
        phones=40,
        frames=20,
        slow_phones=1,
        slow_send_ms=25.0,
        shared_lock=False,
        frame_interval_ms=5.0,
    )

    assert result["fast_seen"] >= 760
    assert result["fast_p95_ms"] <= perf_budget("STREAM_E2E_FAST_P95_MS", 5.0)
    assert result["telemetry"]["dispatch_no_receiver"] == 0
    assert result["telemetry"]["fanout_no_subscriber"] == 0
    assert result["telemetry"]["ws_dropped"] <= perf_budget("STREAM_E2E_WS_DROPS", 5.0)
    assert result["stream_status"]["dedicated_media_ws_ok"] is True
    assert result["stream_status"]["max_media_streams_per_connection"] == 1


@pytest.mark.asyncio
async def test_stream_e2e_100_phone_isolated_media_path_under_budget() -> None:
    result = await _run(
        phones=100,
        frames=20,
        slow_phones=4,
        slow_send_ms=25.0,
        shared_lock=False,
        frame_interval_ms=5.0,
    )

    assert result["fast_seen"] >= 1900
    assert result["fast_p95_ms"] <= perf_budget("STREAM_E2E_100_FAST_P95_MS", 5.0)
    assert result["telemetry"]["dispatch_no_receiver"] == 0
    assert result["telemetry"]["fanout_no_subscriber"] == 0
    assert result["stream_status"]["dedicated_media_ws_ok"] is True
    assert result["stream_status"]["media_ws_active"] == 100
    assert result["stream_status"]["media_streams_active"] == 100
    assert result["stream_status"]["max_media_streams_per_connection"] == 1
