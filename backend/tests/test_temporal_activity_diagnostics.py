from api.routes.device_control.campaign_fleet import _classify_activity_progress


def test_activity_diagnostics_idle_without_running_activity():
    result = _classify_activity_progress(
        status="running",
        running_step=False,
        elapsed_ms=0,
        activity_id=None,
        phase=None,
        side_effect_class=None,
        activity_attempt=0,
    )

    assert result == {
        "activity_state": "idle",
        "stalled_reason": None,
        "stalled_after_ms": 0,
        "stalled_threshold_ms": None,
        "activity_retrying": False,
    }


def test_activity_diagnostics_flags_possible_worker_or_heartbeat_gap():
    result = _classify_activity_progress(
        status="running",
        running_step=True,
        elapsed_ms=130_000,
        activity_id="step:exec-1:tap:attempt:1",
        phase="scheduled",
        side_effect_class="device_effect",
        activity_attempt=1,
    )

    assert result["activity_state"] == "possibly_stalled"
    assert result["stalled_reason"] == "no_worker_pickup_or_activity_heartbeat_gap"
    assert result["stalled_after_ms"] == 10_000
    assert result["stalled_threshold_ms"] == 120_000
    assert result["activity_retrying"] is False


def test_activity_diagnostics_flags_timeout_risk_after_hard_threshold():
    result = _classify_activity_progress(
        status="running",
        running_step=True,
        elapsed_ms=610_000,
        activity_id="batch:exec-1:first:0-9:count:10",
        phase="scheduled_batch",
        side_effect_class="mixed_batch",
        activity_attempt=2,
    )

    assert result["activity_state"] == "timed_out"
    assert result["stalled_reason"] == "heartbeat_timeout_risk"
    assert result["stalled_after_ms"] == 430_000
    assert result["stalled_threshold_ms"] == 180_000
    assert result["activity_retrying"] is True


def test_activity_diagnostics_reports_paused_before_stall_heuristics():
    result = _classify_activity_progress(
        status="paused_on_error",
        running_step=True,
        elapsed_ms=999_000,
        activity_id="step:exec-1:tap:attempt:1",
        phase="scheduled",
        side_effect_class="device_effect",
        activity_attempt=1,
    )

    assert result["activity_state"] == "paused"
    assert result["stalled_reason"] is None
