from __future__ import annotations

import pytest

from scripts.benchmark_media_session_isolation import (
    run_media_session_isolation_benchmark,
)


@pytest.mark.asyncio
async def test_media_session_isolation_benchmark_keeps_healthy_sessions_alive() -> None:
    result = await run_media_session_isolation_benchmark(
        phones=12,
        visible_phones=4,
        fault_every=4,
        noisy_every=3,
        start_ms=1,
        stop_ms=1,
        stats_iterations=2,
    )

    assert result["kind"] == "media_session_isolation_mock"
    assert result["passed"] is True
    assert result["active_after_start"] == 12
    assert result["fatal_injected"] == 3
    assert result["active_after_fatal"] == 9
    assert result["healthy_survivors"] == 9
    assert result["healthy_stopped_by_mistake"] == 0
    assert result["guardrails"] == {
        "all_sessions_started": True,
        "all_fatal_removed": True,
        "no_healthy_stopped": True,
        "clean_stop": True,
    }
