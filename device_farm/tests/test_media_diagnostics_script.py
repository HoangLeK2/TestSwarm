from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "media_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("media_diagnostics", SCRIPT_PATH)
assert SPEC and SPEC.loader
media_diagnostics = importlib.util.module_from_spec(SPEC)
sys.modules["media_diagnostics"] = media_diagnostics
SPEC.loader.exec_module(media_diagnostics)


def _sample(
    *,
    frames: int,
    bytes_: int,
    producer_packets: int,
    consumer_packets: int,
    connected: bool = True,
    real_producers: int = 1,
    consumers: int = 1,
) -> dict:
    return {
        "adapter": {
            "ok": True,
            "data": {
                "active": connected,
                "connected": connected,
                "frames": frames,
                "bytes": bytes_,
                "keyframes": 1,
                "publish_errors": 0,
                "reconnects": 0,
            },
        },
        "publisher": {
            "ok": True,
            "data": {
                "queue_drops": 0,
                "stale_drops": 0,
                "write_errors": 0,
            },
        },
        "go2rtc": {"ok": True},
        "stream": {
            "present": True,
            "real_producer_count": real_producers,
            "consumer_count": consumers,
            "producer_stats": {"packets": producer_packets, "bytes": producer_packets * 1000},
            "consumer_stats": {"packets": consumer_packets, "bytes": consumer_packets * 1000},
        },
    }


def test_stream_name_matches_backend_contract() -> None:
    assert media_diagnostics.stream_name("emulator-5554") == "device-emulator-5554"
    assert media_diagnostics.stream_name(" 1.2_3 ") == "device-1.2_3"
    assert media_diagnostics.stream_name("a/b:c") == "device-a_b_c"
    assert media_diagnostics.stream_name("") == "device-unknown"


def test_classifies_source_stall_when_adapter_counters_stop() -> None:
    samples = [
        _sample(frames=10, bytes_=1000, producer_packets=10, consumer_packets=10),
        _sample(frames=10, bytes_=1000, producer_packets=20, consumer_packets=20),
    ]

    classification, findings = media_diagnostics.classify(samples, 1.0)

    assert classification == "source_stalled"
    assert any("media-adapter" in finding for finding in findings)


def test_classifies_publish_stall_when_go2rtc_producer_does_not_move() -> None:
    samples = [
        _sample(frames=10, bytes_=1000, producer_packets=10, consumer_packets=10),
        _sample(frames=20, bytes_=2000, producer_packets=10, consumer_packets=10),
    ]

    classification, findings = media_diagnostics.classify(samples, 1.0)

    assert classification == "publish_stalled"
    assert any("producer packets" in finding for finding in findings)


def test_classifies_consumer_stall_when_producer_moves_but_consumer_does_not() -> None:
    samples = [
        _sample(frames=10, bytes_=1000, producer_packets=10, consumer_packets=10),
        _sample(frames=20, bytes_=2000, producer_packets=20, consumer_packets=10),
    ]

    classification, findings = media_diagnostics.classify(samples, 1.0)

    assert classification == "go2rtc_consumer_stalled"
    assert any("consumer packets" in finding for finding in findings)


def test_classifies_degraded_when_publisher_stats_move() -> None:
    first = _sample(frames=10, bytes_=1000, producer_packets=10, consumer_packets=10)
    last = _sample(frames=20, bytes_=2000, producer_packets=20, consumer_packets=20)
    last["publisher"]["data"]["stale_drops"] = 2

    classification, findings = media_diagnostics.classify([first, last], 1.0)

    assert classification == "degraded_publish_errors"
    assert any("publish errors" in finding for finding in findings)


def test_summarizes_go2rtc_stream_ignores_placeholder_as_real_producer() -> None:
    stream = {
        "producers": [
            {"url": "rtsp://127.0.0.1:9/placeholder", "receivers": [{"packets": 0, "bytes": 0}]},
            {
                "url": "rtsp://127.0.0.1:8554/device-emulator-5554",
                "protocol": "rtsp+tcp",
                "receivers": [{"packets": 7, "bytes": 7000}],
            },
        ],
        "consumers": [
            {"protocol": "http+udp", "senders": [{"packets": 5, "bytes": 5000}]},
        ],
    }

    summary = media_diagnostics.summarize_go2rtc_stream(stream)

    assert summary["present"] is True
    assert summary["producer_count"] == 2
    assert summary["real_producer_count"] == 1
    assert summary["consumer_count"] == 1
    assert summary["producer_stats"] == {"packets": 7, "bytes": 7000}
    assert summary["consumer_stats"] == {"packets": 5, "bytes": 5000}


def test_docker_warnings_detect_secret_and_candidate_drift_without_leaking_values() -> None:
    diagnostics = {
        "media_adapter": {
            "env": {
                "MEDIA_ADAPTER_GO2RTC_REGISTER_ENABLED": "1",
            }
        },
        "go2rtc": {
            "command_config": {
                "rtsp": {"username": "farm", "password": "running-secret"},
                "webrtc": {"candidates": ["127.0.0.1:8555"]},
            }
        },
    }
    env = {
        "RTSP_USER": "farm",
        "RTSP_PASS": "expected-secret",
        "GO2RTC_WEBRTC_CANDIDATES": '"203.0.113.10:8555","stun:8555"',
    }

    warnings = media_diagnostics.docker_config_warnings(diagnostics, env)
    sanitized = media_diagnostics.sanitize(diagnostics)

    assert any("REGISTER_ENABLED" in warning for warning in warnings)
    assert any("password does not match" in warning for warning in warnings)
    assert any("candidates do not match" in warning for warning in warnings)
    assert "running-secret" not in repr(sanitized)


def test_load_env_file_preserves_candidate_list_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        "GO2RTC_WEBRTC_CANDIDATES='\"203.0.113.10:8555\",\"stun:8555\"'\n",
        encoding="utf-8",
    )

    values = media_diagnostics.load_env_file(env_file)

    assert media_diagnostics.parse_candidate_list(values["GO2RTC_WEBRTC_CANDIDATES"]) == [
        "203.0.113.10:8555",
        "stun:8555",
    ]


def test_exit_code_can_fail_on_config_warnings() -> None:
    assert media_diagnostics.exit_code("healthy", ["drift"], fail_on_warning=True) == 3
    assert media_diagnostics.exit_code("healthy", ["drift"], fail_on_warning=False) == 0
    assert media_diagnostics.exit_code("publish_stalled", [], fail_on_warning=False) == 2


def test_sanitize_keeps_keyframe_counters_visible() -> None:
    payload = {
        "keyframes": 3,
        "rtsp_password": "secret",
        "nested": {"api_key": "secret-key"},
    }

    sanitized = media_diagnostics.sanitize(payload)

    assert sanitized["keyframes"] == 3
    assert sanitized["rtsp_password"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["api_key"] == "[REDACTED_SECRET]"
