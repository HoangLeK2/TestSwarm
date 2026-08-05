"""Thin HTTP client for stream intent handled by the Go media adapter."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("relay.media_adapter")

_DISABLED_LOGGED = False


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def enabled() -> bool:
    return _env_enabled("MEDIA_ADAPTER_ENABLED", default=False)


def http_base_url() -> str:
    raw = os.environ.get("MEDIA_ADAPTER_HTTP_URL", "").strip().rstrip("/")
    if raw:
        return raw
    host = (os.environ.get("MEDIA_ADAPTER_HTTP_HOST") or "127.0.0.1").strip()
    port = (os.environ.get("MEDIA_ADAPTER_HTTP_PORT") or "8878").strip()
    return f"http://{host or '127.0.0.1'}:{port or '8878'}"


def direct_scrcpy_enabled() -> bool:
    return enabled() and _env_enabled("MEDIA_ADAPTER_DIRECT_SCRCPY_ENABLED", default=False)


def owns_scrcpy_enabled() -> bool:
    return direct_scrcpy_enabled() and _env_enabled("MEDIA_ADAPTER_OWNS_SCRCPY", default=True)


def log_disabled_once() -> None:
    global _DISABLED_LOGGED
    if not enabled():
        if not _DISABLED_LOGGED:
            logger.info("media adapter disabled")
            _DISABLED_LOGGED = True


def start_direct_scrcpy_stream(
    *,
    serial: str,
    host: str = "",
    port: int = 0,
    control: bool = True,
    owns_scrcpy: bool | None = None,
    max_fps: int | None = None,
    max_width: int | None = None,
    bitrate: int | None = None,
    video_codec: str | None = None,
    low_latency: bool = False,
) -> dict:
    if owns_scrcpy is None:
        owns_scrcpy = owns_scrcpy_enabled()
    payload = {
        "host": host,
        "port": port,
        "control": control,
        "owns_scrcpy": owns_scrcpy,
        "low_latency": low_latency,
    }
    if max_fps is not None:
        payload["max_fps"] = max_fps
    if max_width is not None:
        payload["max_width"] = max_width
    if bitrate is not None:
        payload["bitrate"] = bitrate
    if video_codec:
        payload["video_codec"] = video_codec
    return _json_request(
        "POST",
        f"/v1/scrcpy/streams/{urllib.parse.quote(serial, safe='')}/start",
        payload,
        timeout=1.5,
    )


def stop_direct_scrcpy_stream(serial: str) -> None:
    try:
        _json_request(
            "POST",
            f"/v1/scrcpy/streams/{urllib.parse.quote(serial, safe='')}/stop",
            {},
            timeout=0.8,
        )
    except Exception as exc:
        logger.debug("media adapter direct stop failed serial=%s: %s", serial, exc)


def request_direct_keyframe(serial: str) -> bool:
    try:
        _json_request(
            "POST",
            f"/v1/scrcpy/streams/{urllib.parse.quote(serial, safe='')}/keyframe",
            {},
            timeout=0.8,
        )
        return True
    except Exception as exc:
        logger.debug("media adapter keyframe request failed serial=%s: %s", serial, exc)
        return False


def direct_scrcpy_status(serial: str) -> dict | None:
    try:
        return _json_request(
            "GET",
            f"/v1/scrcpy/streams/{urllib.parse.quote(serial, safe='')}/status",
            None,
            timeout=0.8,
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def per_serial_env(name: str, serial: str, default: str = "") -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in serial)
    return os.getenv(f"{name}__{safe}", os.getenv(name, default)).strip()


def _json_request(
    method: str,
    path: str,
    payload: dict | None,
    *,
    timeout: float,
) -> dict:
    base = http_base_url()
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))
