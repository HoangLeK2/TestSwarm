from __future__ import annotations

import pytest

from scripts.benchmark_stream_ws_isolation import _run
from tests.perf_assertions import perf_budget


@pytest.mark.asyncio
async def test_stream_ws_isolation_keeps_fast_phones_below_latency_budget() -> None:
    result = await _run(
        phones=40,
        frames=20,
        slow_phones=1,
        slow_send_ms=25.0,
        shared_lock=False,
        lock_wait_ms=8.0,
        frame_interval_ms=5.0,
    )

    assert result["fast_seen"] >= 760
    assert result["fast_p95_ms"] <= perf_budget("STREAM_WS_ISOLATION_FAST_P95_MS", 5.0)
    assert result["producer_drops"] <= perf_budget("STREAM_WS_ISOLATION_PRODUCER_DROPS", 20.0)
