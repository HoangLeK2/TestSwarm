from __future__ import annotations

import pytest

from scripts import benchmark_agent_boot_mixed_soak as bench


@pytest.mark.asyncio
async def test_agent_boot_mixed_soak_passes_small_mock_fleet() -> None:
    result = await bench.run_mixed_soak(
        phones=12,
        visible_phones=4,
        duration_s=0.3,
        stream_fps=12,
        stream_payload_bytes=2_000,
        video_shards=4,
        noisy_fps_multiplier=4,
        u2_global_limit=8,
        u2_background_limit=6,
        u2_background_per_phone=1,
        u2_touch_per_visible=1,
        forward_attempts_per_serial=6,
        forward_concurrency=24,
        forward_adb_delay_ms=1.0,
        forward_cooldown_s=2.0,
    )

    assert result["kind"] == "agent_boot_mixed_soak_mock"
    assert result["passed"] is True
    assert result["guardrails"] == {
        "stream": True,
        "u2": True,
        "forward": True,
    }
    assert result["forward"]["adb_forward_create_calls"] == 12
    assert result["forward"]["create_cooldown_skip"] == 60
