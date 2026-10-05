from __future__ import annotations

from runtime.stream_telemetry import StreamTelemetry


def test_stream_telemetry_records_stream_path_aggregate_and_resets() -> None:
    telemetry = StreamTelemetry()

    telemetry.record_dispatch(push_ms=2.4)
    telemetry.record_dispatch(no_receiver=True)
    telemetry.record_dispatch(push_error=True)
    telemetry.record_fanout(
        subscribers=2,
        frame_bytes=512,
        elapsed_ms=3.2,
        is_key=True,
    )
    telemetry.record_fanout(
        subscribers=0,
        frame_bytes=64,
        elapsed_ms=1.0,
        is_config=True,
    )
    telemetry.record_ws_send(wait_ms=1.2, send_ms=2.2)
    telemetry.record_ws_send(wait_ms=60.0, dropped=True)

    snapshot = telemetry.snapshot(reset=True)

    assert snapshot["dispatch_frames"] == 3
    assert snapshot["dispatch_no_receiver"] == 1
    assert snapshot["dispatch_push_errors"] == 1
    assert snapshot["dispatch_push_p95_ms"] >= 2
    assert snapshot["fanout_frames"] == 2
    assert snapshot["fanout_configs"] == 1
    assert snapshot["fanout_keyframes"] == 1
    assert snapshot["fanout_no_subscriber"] == 1
    assert snapshot["fanout_avg_subscribers"] == 1.0
    assert snapshot["fanout_max_subscribers"] == 2
    assert snapshot["fanout_frame_bytes"] == 576
    assert snapshot["ws_sent"] == 1
    assert snapshot["ws_dropped"] == 1
    assert snapshot["ws_send_wait_p95_ms"] >= 50
    assert snapshot["ws_send_p95_ms"] >= 2

    assert telemetry.snapshot()["dispatch_frames"] == 0
