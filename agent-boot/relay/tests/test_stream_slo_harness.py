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
        max_normal_phone_p95_delta_ms=5,
    )

    assert report.passed


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
