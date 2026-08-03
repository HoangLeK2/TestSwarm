from __future__ import annotations

import pytest

from relay.stream_slo_harness import (
    MockFleetConfig,
    StreamSloThresholds,
    run_mock_fleet,
    run_mock_isolation_probe,
)


@pytest.mark.asyncio
async def test_nominal_mock_fleet_meets_stream_slos() -> None:
    report = await run_mock_fleet(
        MockFleetConfig(
            phones=4,
            duration_s=0.4,
            fps=20,
            payload_bytes=1_024,
            idr_response_ms=20,
        ),
        StreamSloThresholds(
            handoff_p95_ms=10,
            queue_age_p95_ms=50,
            idr_recovery_p95_ms=300,
        ),
    )

    assert report.slo_pass == {
        "command_loss": True,
        "handoff_p95": True,
        "idr_recovery_p95": True,
        "queue_age_p95": True,
    }
    assert report.commands_sent == report.commands_delivered > 0


@pytest.mark.asyncio
async def test_noisy_phone_does_not_raise_other_latency_at_120_phones() -> None:
    report = await run_mock_isolation_probe(
        MockFleetConfig(
            phones=120,
            duration_s=1.0,
            fps=12,
            payload_bytes=50_000,
            idr_response_ms=20,
        ),
        noisy_fps_multiplier=8,
        # This all-stream stress uses 120 real producer threads. Keep the
        # absolute stream SLO strict, but allow scheduler jitter in the
        # cross-run per-phone delta. The stricter 5 ms isolation budget is
        # covered by the visible-subset production-shape test below.
        max_normal_phone_p95_delta_ms=15,
    )

    assert report.passed


@pytest.mark.asyncio
async def test_offscreen_phone_chatter_does_not_raise_visible_stream_latency() -> None:
    report = await run_mock_isolation_probe(
        MockFleetConfig(
            phones=100,
            visible_phones=8,
            duration_s=0.8,
            fps=18,
            payload_bytes=20_000,
            idr_response_ms=20,
            command_interval_s=0.1,
        ),
        noisy_fps_multiplier=12,
        max_normal_phone_p95_delta_ms=5,
        thresholds=StreamSloThresholds(
            handoff_p95_ms=10,
            queue_age_p95_ms=50,
            idr_recovery_p95_ms=300,
        ),
    )

    assert report.passed
    assert report.noisy_serial == "mock-phone-008"
    assert report.noisy_serial not in report.noisy_run.per_phone_queue_age_p95_ms
    assert report.noisy_run.phones == 100
    assert report.noisy_run.visible_phones == 8
    assert report.noisy_run.command_loss == 0
    assert report.noisy_run.idr_recoveries == 8


@pytest.mark.asyncio
async def test_video_shards_protect_visible_stream_under_reliable_backpressure() -> None:
    report = await run_mock_fleet(
        MockFleetConfig(
            phones=60,
            visible_phones=4,
            video_shards=2,
            duration_s=0.5,
            fps=18,
            payload_bytes=20_000,
            idr_response_ms=30,
            command_interval_s=0.05,
            consumer_delay_ms=2,
        ),
        StreamSloThresholds(
            handoff_p95_ms=10,
            queue_age_p95_ms=50,
            idr_recovery_p95_ms=300,
        ),
    )

    assert report.passed
    assert report.video_shards == 2
    assert report.phones == 60
    assert report.visible_phones == 4
    assert report.command_loss == 0
    assert report.queue_age_p95_ms < 50


@pytest.mark.asyncio
async def test_slow_idr_response_fails_recovery_slo() -> None:
    report = await run_mock_fleet(
        MockFleetConfig(
            phones=2,
            duration_s=0.3,
            fps=20,
            payload_bytes=1_024,
            idr_response_ms=20,
        ),
        StreamSloThresholds(idr_recovery_p95_ms=5),
    )

    assert report.slo_pass["idr_recovery_p95"] is False
