from __future__ import annotations

import sys

from scripts import stress_temporal_capacity
from scripts.stress_temporal_capacity import WaveResult, _meets_schedule_to_start_budget


def test_slot_gate_uses_p95_queue_delay_instead_of_single_wall_time_outlier():
    result = WaveResult(
        concurrency=120,
        payload_delay_ms=5_000,
        ok=120,
        wall_s=7.4,
        latencies_s=([5.5] * 119) + [7.4],
    )

    assert result.p95_queue_delay_s == 0.5
    assert _meets_schedule_to_start_budget(result, max_queue_delay_s=2.0)


def test_slot_gate_fails_when_p95_queue_delay_exceeds_budget():
    result = WaveResult(
        concurrency=120,
        payload_delay_ms=5_000,
        ok=120,
        wall_s=8.0,
        latencies_s=[7.5] * 120,
    )

    assert not _meets_schedule_to_start_budget(result, max_queue_delay_s=2.0)


def test_harness_defaults_match_recommended_database_pools(monkeypatch):
    captured = {}
    for name in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_ACTIVITY_POOL_SIZE",
        "DB_ACTIVITY_MAX_OVERFLOW",
    ):
        monkeypatch.delenv(name, raising=False)

    async def fake_async_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(stress_temporal_capacity, "async_main", fake_async_main)
    monkeypatch.setattr(sys, "argv", ["stress_temporal_capacity.py"])

    assert stress_temporal_capacity.main() == 0
    args = captured["args"]
    assert args.db_pool_size == 12
    assert args.db_max_overflow == 3
    assert args.db_activity_pool_size == 4
    assert args.db_activity_max_overflow == 0
