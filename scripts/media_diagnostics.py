#!/usr/bin/env python3
"""Collect media-plane diagnostics for one Device Farm serial.

The probe is intentionally dependency-free so it can run on a developer laptop
or a deployment host without installing the backend package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


UNSAFE_STREAM_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
SECRET_KEYS = {"RTSP_PASS", "PASSWORD", "PASS", "TOKEN", "SECRET", "API_KEY"}
DEFAULT_CONFIG_KEYS = (
    "MEDIA_ADAPTER_GO2RTC_REGISTER_ENABLED",
    "MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE",
    "MEDIA_ADAPTER_REMOTE_RTSP_QUEUE",
    "MEDIA_ADAPTER_STALE_PACKET_MS",
    "MEDIA_ADAPTER_INPUT_FPS",
    "DEVICE_FARM_GO2RTC_URL",
    "GO2RTC_WEBRTC_CANDIDATES",
    "RTSP_USER",
    "RTSP_PASS",
)


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    data: Any = None
    error: str | None = None
    elapsed_ms: int | None = None


def stream_name(serial: str) -> str:
    safe = UNSAFE_STREAM_NAME.sub("_", serial.strip())
    return f"device-{safe or 'unknown'}"


def http_json(url: str, timeout: float) -> FetchResult:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return FetchResult(ok=False, error=str(exc), elapsed_ms=_elapsed_ms(started))
    try:
        return FetchResult(ok=True, data=json.loads(body), elapsed_ms=_elapsed_ms(started))
    except json.JSONDecodeError as exc:
        return FetchResult(ok=False, error=f"invalid json: {exc}", elapsed_ms=_elapsed_ms(started))


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def collect_sample(
    serial: str,
    adapter_url: str,
    go2rtc_url: str,
    timeout: float,
    *,
    go2rtc_container: str | None = None,
) -> dict[str, Any]:
    name = stream_name(serial)
    adapter = http_json(
        join_url(adapter_url, f"/v1/scrcpy/streams/{urllib.parse.quote(serial, safe='')}/status"),
        timeout,
    )
    publisher = http_json(join_url(adapter_url, "/v1/rtsp/publisher/status"), timeout)
    go2rtc = http_json(join_url(go2rtc_url, "/api/streams"), timeout)
    go2rtc_via = "http"
    if not go2rtc.ok and go2rtc_container:
        go2rtc = docker_exec_json(
            go2rtc_container,
            "http://127.0.0.1:1984/api/streams",
            timeout,
        )
        go2rtc_via = "docker_exec"
    stream = extract_go2rtc_stream(go2rtc.data, name) if go2rtc.ok else None
    return {
        "ts_unix_ms": int(time.time() * 1000),
        "adapter": result_to_json(adapter),
        "publisher": result_to_json(publisher),
        "go2rtc": result_to_json(go2rtc, include_data=False) | {"via": go2rtc_via},
        "stream": summarize_go2rtc_stream(stream),
    }


def result_to_json(result: FetchResult, *, include_data: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": result.ok}
    if result.elapsed_ms is not None:
        out["elapsed_ms"] = result.elapsed_ms
    if result.error:
        out["error"] = result.error
    if include_data and result.ok:
        out["data"] = result.data
    return out


def extract_go2rtc_stream(payload: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = []
    streams = payload.get("streams")
    if isinstance(streams, dict):
        candidates.append(streams)
    candidates.append(payload)
    for item in candidates:
        stream = item.get(name) if isinstance(item, dict) else None
        if isinstance(stream, dict):
            return stream
    return None


def summarize_go2rtc_stream(stream: dict[str, Any] | None) -> dict[str, Any]:
    if not stream:
        return {"present": False}
    producers = _as_list(stream.get("producers"))
    consumers = _as_list(stream.get("consumers"))
    real_producers = [
        producer
        for producer in producers
        if "127.0.0.1:9/placeholder" not in str(producer.get("url", ""))
    ]
    return {
        "present": True,
        "producer_count": len(producers),
        "real_producer_count": len(real_producers),
        "consumer_count": len(consumers),
        "producer_stats": sum_packet_stats(producers),
        "consumer_stats": sum_packet_stats(consumers),
        "producer_protocols": sorted(_compact_strings(item.get("protocol") for item in producers)),
        "consumer_protocols": sorted(_compact_strings(item.get("protocol") for item in consumers)),
    }


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact_strings(values: Any) -> set[str]:
    return {str(value) for value in values if value}


def sum_packet_stats(value: Any) -> dict[str, int]:
    totals = {"bytes": 0, "packets": 0}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("bytes", "packets"):
                item = node.get(key)
                if isinstance(item, int):
                    totals[key] += item
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return totals


def classify(samples: list[dict[str, Any]], interval_seconds: float) -> tuple[str, list[str]]:
    findings: list[str] = []
    if not samples:
        return "no_samples", ["probe did not collect any sample"]
    first = samples[0]
    last = samples[-1]
    first_adapter = _adapter_data(first)
    last_adapter = _adapter_data(last)
    if not last["adapter"].get("ok"):
        return "adapter_unreachable", [f"adapter status failed: {last['adapter'].get('error')}"]
    if not last["go2rtc"].get("ok"):
        return "go2rtc_unreachable", [f"go2rtc streams failed: {last['go2rtc'].get('error')}"]
    if not last_adapter:
        return "adapter_status_missing", ["adapter status response did not contain stream data"]
    connected = bool(last_adapter.get("connected"))
    active = bool(last_adapter.get("active", connected))
    if not connected or not active:
        findings.append("media-adapter reports the scrcpy stream is not connected")
        return "source_stalled", findings

    deltas = compute_deltas(first, last)
    if len(samples) < 2:
        findings.append("only one sample was collected; packet/frame deltas are unavailable")
    else:
        if deltas["adapter_frames"] <= 0 or deltas["adapter_bytes"] <= 0:
            findings.append("media-adapter frame or byte counters did not move")
            return "source_stalled", findings

    last_frame_age_ms = _last_frame_age_ms(last_adapter)
    if last_frame_age_ms is not None and last_frame_age_ms > max(2500, int(interval_seconds * 2500)):
        findings.append(f"last media-adapter frame is stale: {last_frame_age_ms}ms old")
        return "source_frame_gap", findings

    stream = last.get("stream") or {}
    if not stream.get("present"):
        findings.append("go2rtc does not expose the expected stream")
        return "go2rtc_stream_missing", findings
    if int(stream.get("real_producer_count") or 0) <= 0:
        findings.append("go2rtc has no real RTSP producer for the stream")
        return "go2rtc_source_missing", findings
    if len(samples) >= 2 and deltas["producer_packets"] <= 0:
        findings.append("media-adapter counters moved but go2rtc producer packets did not")
        return "publish_stalled", findings
    if int(stream.get("consumer_count") or 0) <= 0:
        findings.append("no WebRTC consumer is currently attached")
        return "no_consumer", findings
    if len(samples) >= 2 and deltas["consumer_packets"] <= 0:
        findings.append("go2rtc receives producer packets but consumer packets did not move")
        return "go2rtc_consumer_stalled", findings
    if len(samples) >= 2 and (
        deltas["adapter_publish_errors"] > 0 or deltas["adapter_reconnects"] > 0
        or deltas["publisher_write_errors"] > 0 or deltas["publisher_queue_drops"] > 0
        or deltas["publisher_stale_drops"] > 0
    ):
        findings.append("media-adapter reported publish errors or scrcpy reconnects during the probe")
        return "degraded_publish_errors", findings
    findings.append("source, RTSP producer, and WebRTC consumer counters moved")
    return "healthy", findings


def _adapter_data(sample: dict[str, Any]) -> dict[str, Any]:
    data = sample.get("adapter", {}).get("data")
    return data if isinstance(data, dict) else {}


def _last_frame_age_ms(status: dict[str, Any]) -> int | None:
    last = status.get("last_frame_unix_ms")
    if not isinstance(last, int) or last <= 0:
        return None
    return int(time.time() * 1000) - last


def compute_deltas(first: dict[str, Any], last: dict[str, Any]) -> dict[str, int]:
    first_adapter = _adapter_data(first)
    last_adapter = _adapter_data(last)
    first_stream = first.get("stream") or {}
    last_stream = last.get("stream") or {}
    return {
        "adapter_frames": _delta(first_adapter, last_adapter, "frames"),
        "adapter_bytes": _delta(first_adapter, last_adapter, "bytes"),
        "adapter_keyframes": _delta(first_adapter, last_adapter, "keyframes"),
        "adapter_publish_errors": _delta(first_adapter, last_adapter, "publish_errors"),
        "adapter_reconnects": _delta(first_adapter, last_adapter, "reconnects"),
        "publisher_queue_drops": _delta(_publisher_data(first), _publisher_data(last), "queue_drops"),
        "publisher_stale_drops": _delta(_publisher_data(first), _publisher_data(last), "stale_drops"),
        "publisher_write_errors": _delta(_publisher_data(first), _publisher_data(last), "write_errors"),
        "producer_packets": _delta_stats(first_stream, last_stream, "producer_stats", "packets"),
        "producer_bytes": _delta_stats(first_stream, last_stream, "producer_stats", "bytes"),
        "consumer_packets": _delta_stats(first_stream, last_stream, "consumer_stats", "packets"),
        "consumer_bytes": _delta_stats(first_stream, last_stream, "consumer_stats", "bytes"),
    }


def _publisher_data(sample: dict[str, Any]) -> dict[str, Any]:
    data = sample.get("publisher", {}).get("data")
    return data if isinstance(data, dict) else {}


def _delta(first: dict[str, Any], last: dict[str, Any], key: str) -> int:
    return int(last.get(key) or 0) - int(first.get(key) or 0)


def _delta_stats(first: dict[str, Any], last: dict[str, Any], group: str, key: str) -> int:
    first_group = first.get(group) if isinstance(first.get(group), dict) else {}
    last_group = last.get(group) if isinstance(last.get(group), dict) else {}
    return int(last_group.get(key) or 0) - int(first_group.get(key) or 0)


def load_env_file(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = unquote_env_value(value.strip())
    return values


def unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def inspect_docker(go2rtc_container: str, adapter_container: str, env_values: dict[str, str]) -> dict[str, Any]:
    go2rtc = docker_inspect(go2rtc_container)
    adapter = docker_inspect(adapter_container)
    diagnostics = {
        "go2rtc": summarize_go2rtc_container(go2rtc.data) if go2rtc.ok else {"ok": False, "error": go2rtc.error},
        "media_adapter": summarize_env_container(adapter.data, DEFAULT_CONFIG_KEYS)
        if adapter.ok
        else {"ok": False, "error": adapter.error},
        "warnings": [],
    }
    diagnostics["warnings"] = docker_config_warnings(diagnostics, env_values)
    return diagnostics


def docker_inspect(container: str) -> FetchResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["docker", "inspect", container],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return FetchResult(ok=False, error=str(exc), elapsed_ms=_elapsed_ms(started))
    if proc.returncode != 0:
        return FetchResult(ok=False, error=proc.stderr.strip() or proc.stdout.strip(), elapsed_ms=_elapsed_ms(started))
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return FetchResult(ok=False, error=f"invalid docker inspect json: {exc}", elapsed_ms=_elapsed_ms(started))
    item = data[0] if isinstance(data, list) and data else None
    return FetchResult(ok=isinstance(item, dict), data=item, elapsed_ms=_elapsed_ms(started))


def docker_exec_json(container: str, url: str, timeout: float) -> FetchResult:
    started = time.monotonic()
    command = [
        "docker",
        "exec",
        container,
        "wget",
        "-qO-",
        f"--timeout={max(1, int(timeout))}",
        url,
    ]
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(2, timeout + 1),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return FetchResult(ok=False, error=str(exc), elapsed_ms=_elapsed_ms(started))
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"docker exec exited {proc.returncode}"
        return FetchResult(ok=False, error=message, elapsed_ms=_elapsed_ms(started))
    try:
        return FetchResult(ok=True, data=json.loads(proc.stdout), elapsed_ms=_elapsed_ms(started))
    except json.JSONDecodeError as exc:
        return FetchResult(ok=False, error=f"invalid docker exec json: {exc}", elapsed_ms=_elapsed_ms(started))


def summarize_go2rtc_container(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"ok": False, "error": "missing docker inspect data"}
    cmd = data.get("Config", {}).get("Cmd")
    config = parse_go2rtc_command_config(cmd if isinstance(cmd, list) else [])
    return {
        "ok": True,
        "image": data.get("Config", {}).get("Image"),
        "ports": data.get("NetworkSettings", {}).get("Ports") or {},
        "command_config": sanitize(config),
    }


def summarize_env_container(data: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"ok": False, "error": "missing docker inspect data"}
    env = docker_env_map(data)
    return {
        "ok": True,
        "image": data.get("Config", {}).get("Image"),
        "env": sanitize({key: env.get(key) for key in keys if key in env}),
    }


def parse_go2rtc_command_config(cmd: list[str]) -> dict[str, Any]:
    for item in cmd:
        value = item.strip()
        if value.startswith("{") and "webrtc" in value:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                continue
            return parsed if isinstance(parsed, dict) else {}
    return {}


def docker_env_map(data: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    env = data.get("Config", {}).get("Env")
    if not isinstance(env, list):
        return out
    for item in env:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            out[key] = value
    return out


def docker_config_warnings(diagnostics: dict[str, Any], env_values: dict[str, str]) -> list[str]:
    warnings: list[str] = []
    adapter_env = diagnostics.get("media_adapter", {}).get("env") or {}
    register_enabled = adapter_env.get("MEDIA_ADAPTER_GO2RTC_REGISTER_ENABLED")
    if register_enabled not in ("0", "false", "False", False):
        warnings.append("MEDIA_ADAPTER_GO2RTC_REGISTER_ENABLED should be 0 for backend-signaled RTSP push deployments")
    if "MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE" not in adapter_env:
        warnings.append("media-adapter container does not expose MEDIA_ADAPTER_GO2RTC_RTSP_PUBLISH_TEMPLATE")

    command_config = diagnostics.get("go2rtc", {}).get("command_config") or {}
    rtsp = command_config.get("rtsp") if isinstance(command_config.get("rtsp"), dict) else {}
    webrtc = command_config.get("webrtc") if isinstance(command_config.get("webrtc"), dict) else {}
    if env_values:
        if "RTSP_USER" in env_values and rtsp.get("username") != env_values["RTSP_USER"]:
            warnings.append("running go2rtc RTSP username does not match env file")
        if "RTSP_PASS" in env_values and secret_fingerprint(rtsp.get("password")) != secret_fingerprint(env_values["RTSP_PASS"]):
            warnings.append("running go2rtc RTSP password does not match env file")
        expected_candidates = parse_candidate_list(env_values.get("GO2RTC_WEBRTC_CANDIDATES", ""))
        running_candidates = webrtc.get("candidates")
        if expected_candidates and running_candidates != expected_candidates:
            warnings.append("running go2rtc WebRTC candidates do not match env file")
    return warnings


def parse_candidate_list(value: str) -> list[str]:
    stripped = value.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(f"[{stripped}]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed if item]


def secret_fingerprint(value: Any) -> str:
    if value is None:
        return ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if is_secret_key(key):
                out[key] = "[REDACTED_SECRET]"
            else:
                out[key] = sanitize(item)
        return out
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_url(value)
    return value


def is_secret_key(key: str) -> bool:
    upper = key.upper()
    return upper in SECRET_KEYS or upper.endswith("_PASSWORD") or upper.endswith("_TOKEN") or upper.endswith("_SECRET")


def redact_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme or not parsed.netloc or "@" not in parsed.netloc:
        return value
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Device Farm go2rtc/media-adapter stream health")
    parser.add_argument("serial", help="ADB serial to inspect, for example emulator-5554")
    parser.add_argument("--adapter-url", default=os.environ.get("MEDIA_ADAPTER_HTTP_URL", "http://127.0.0.1:8878"))
    parser.add_argument(
        "--go2rtc-url",
        default=os.environ.get("DEVICE_FARM_GO2RTC_URL") or os.environ.get("GO2RTC_URL") or "http://127.0.0.1:1984",
    )
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--env-file", type=Path, default=None, help="Optional .env/deploy.env for drift checks")
    parser.add_argument("--docker", action="store_true", help="Inspect go2rtc/media-adapter containers")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit non-zero when Docker/env drift is detected")
    parser.add_argument("--go2rtc-container", default="device-farm-go2rtc-1")
    parser.add_argument("--adapter-container", default="media-adapter")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sample_count = max(1, args.samples)
    samples: list[dict[str, Any]] = []
    for index in range(sample_count):
        samples.append(
            collect_sample(
                args.serial,
                args.adapter_url,
                args.go2rtc_url,
                args.timeout,
                go2rtc_container=args.go2rtc_container if args.docker else None,
            )
        )
        if index + 1 < sample_count:
            time.sleep(max(0.1, args.interval))
    classification, findings = classify(samples, args.interval)
    report: dict[str, Any] = {
        "serial": args.serial,
        "stream_name": stream_name(args.serial),
        "classification": classification,
        "findings": findings,
        "deltas": compute_deltas(samples[0], samples[-1]) if samples else {},
        "config": {
            "adapter_url": redact_url(args.adapter_url),
            "go2rtc_url": redact_url(args.go2rtc_url),
            "samples": sample_count,
            "interval_seconds": args.interval,
            "timeout_seconds": args.timeout,
        },
        "samples": samples,
    }
    env_values = load_env_file(args.env_file)
    docker_warnings: list[str] = []
    if args.docker:
        report["docker"] = inspect_docker(args.go2rtc_container, args.adapter_container, env_values)
        docker_warnings = report["docker"].get("warnings") or []
    print(json.dumps(sanitize(report), ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code(classification, docker_warnings, fail_on_warning=args.fail_on_warning)


def exit_code(classification: str, warnings: list[str], *, fail_on_warning: bool) -> int:
    if fail_on_warning and warnings:
        return 3
    return 0 if classification in {"healthy", "no_consumer"} else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
