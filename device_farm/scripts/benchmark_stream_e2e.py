from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field

from core.config import Config
from runtime.core.device_client import DeviceClient
from runtime.stream_telemetry import stream_telemetry
from runtime.transports.adb_relay_server import AdbRelayManager
from web.ws import WebSocketManager


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    pos = max(0.0, min(1.0, p)) * (len(vals) - 1)
    idx = int(pos)
    frac = pos - idx
    if idx >= len(vals) - 1:
        return vals[-1]
    return vals[idx] + (vals[idx + 1] - vals[idx]) * frac


class _H264Receiver:
    def __init__(self, device: DeviceClient) -> None:
        self.device = device

    def push_frame(
        self,
        data: bytes,
        _pts_raw: int,
        width: int,
        height: int,
        *,
        is_config: bool = False,
        is_keyframe: bool = False,
        pts: int = 0,
    ) -> None:
        if is_config:
            self.device.on_agent_h264_config(data, width, height)
            return
        self.device.on_agent_h264_video(data, is_key=is_keyframe, pts_us=pts)


class _DeviceManager:
    def __init__(self, devices: list[DeviceClient]) -> None:
        self._by_serial = {device.serial: device for device in devices}

    def get_device(self, serial: str):
        return self._by_serial.get(serial)

    def all_devices(self):
        return list(self._by_serial.values())


@dataclass
class _TimedWebSocket:
    slow_serials: set[str]
    slow_send_ms: float
    put_times: dict[tuple[str, int], float]
    lags_by_serial: dict[str, list[float]] = field(default_factory=dict)
    sent_total: int = 0

    async def send_bytes(self, frame: bytes) -> None:
        parsed = _parse_h264_frame(frame)
        if parsed is None:
            return
        serial, pts_us = parsed
        if serial in self.slow_serials:
            await asyncio.sleep(self.slow_send_ms / 1000.0)
        put_ts = self.put_times.get((serial, pts_us))
        if put_ts is not None:
            self.lags_by_serial.setdefault(serial, []).append(
                (time.perf_counter() - put_ts) * 1000.0
            )
        self.sent_total += 1


def _parse_h264_frame(frame: bytes) -> tuple[str, int] | None:
    if not frame or frame[0] != 0x11:
        return None
    serial_len = int(frame[1])
    if len(frame) < 2 + serial_len + 4 + 9:
        return None
    serial = frame[2 : 2 + serial_len].decode("utf-8", errors="replace")
    pts_off = 2 + serial_len + 4 + 1
    pts_hi = int.from_bytes(frame[pts_off : pts_off + 4], "big")
    pts_lo = int.from_bytes(frame[pts_off + 4 : pts_off + 8], "big")
    pts_us = (pts_hi << 32) | pts_lo
    return serial, pts_us


def _publish_frame(relay: AdbRelayManager, serial: str, pts_us: int, *, is_key: bool) -> None:
    relay.dispatch_scrcpy_frame(
        serial,
        b"\x00\x00\x00\x04data",
        pts_us,
        360,
        800,
        is_config=False,
        is_keyframe=is_key,
        pts=pts_us,
    )


async def _run(
    *,
    phones: int,
    frames: int,
    slow_phones: int,
    slow_send_ms: float,
    shared_lock: bool,
    frame_interval_ms: float,
) -> dict:
    stream_telemetry.reset()
    loop = asyncio.get_running_loop()
    serials = [f"SN{i:04d}" for i in range(phones)]
    devices = [DeviceClient(serial=serial, index=i, config=Config()) for i, serial in enumerate(serials)]
    for device in devices:
        device._loop = loop
        device.screen_width = 360
        device.screen_height = 800

    relay = AdbRelayManager()
    for device in devices:
        relay.register_scrcpy_receiver(device.serial, _H264Receiver(device))

    slow_serials = set(serials[:slow_phones])
    put_times: dict[tuple[str, int], float] = {}
    ws = _TimedWebSocket(
        slow_serials=slow_serials,
        slow_send_ms=slow_send_ms,
        put_times=put_times,
    )
    ws_manager = WebSocketManager(_DeviceManager(devices), db_enabled=False, read_only=False)
    one_lock = asyncio.Lock()
    sender_tasks: list[asyncio.Task] = []
    for device in devices:
        lock = one_lock if shared_lock else asyncio.Lock()
        conn_id = "bench-shared" if shared_lock else f"bench-{device.serial}"
        task = asyncio.create_task(
            ws_manager._device_sender(ws, device, lock, conn_id=conn_id)
        )
        setattr(task, "_device_serial", device.serial)
        setattr(task, "_connection_id", conn_id)
        ws_manager._conn_sender_groups.setdefault(conn_id, []).append(task)
        ws_manager._conn_sessions.setdefault(conn_id, f"benchmark-{conn_id}")
        sender_tasks.append(task)

    started = time.perf_counter()
    try:
        for _ in range(100):
            if all(device._frame_queues for device in devices):
                break
            await asyncio.sleep(0.005)
        if not all(device._frame_queues for device in devices):
            raise RuntimeError("device sender queues were not ready")

        for seq in range(frames):
            for serial in serials:
                put_times[(serial, seq)] = time.perf_counter()
                _publish_frame(relay, serial, seq, is_key=seq % 15 == 0)
            await asyncio.sleep(frame_interval_ms / 1000.0)

        deadline = time.perf_counter() + 3.0
        expected_fast = (phones - slow_phones) * frames
        while time.perf_counter() < deadline:
            fast_seen = sum(
                len(values)
                for serial, values in ws.lags_by_serial.items()
                if serial not in slow_serials
            )
            if fast_seen >= expected_fast:
                break
            await asyncio.sleep(0.005)

        fast_lags = [
            lag
            for serial, values in ws.lags_by_serial.items()
            if serial not in slow_serials
            for lag in values
        ]
        slow_lags = [
            lag
            for serial, values in ws.lags_by_serial.items()
            if serial in slow_serials
            for lag in values
        ]
        telemetry = stream_telemetry.snapshot(reset=True)
        raw_stream_status = ws_manager.stream_runtime_status()
        sample_media_ws = []
        for item in raw_stream_status["media_ws_per_connection"][:3]:
            serials = list(item["serials"])
            sample_media_ws.append(
                {
                    **item,
                    "serials": serials[:5],
                    "serials_truncated": max(0, len(serials) - 5),
                }
            )
        stream_status = {
            "dedicated_media_ws_ok": raw_stream_status["dedicated_media_ws_ok"],
            "media_ws_active": raw_stream_status["media_ws_active"],
            "media_streams_active": raw_stream_status["media_streams_active"],
            "max_media_streams_per_connection": raw_stream_status[
                "max_media_streams_per_connection"
            ],
            "shared_media_ws_connections": raw_stream_status[
                "shared_media_ws_connections"
            ],
            "sender_started_total": raw_stream_status["sender_started_total"],
            "sender_stopped_total": raw_stream_status["sender_stopped_total"],
            "sender_sent_total": raw_stream_status["sender_sent_total"],
            "sender_dropped_total": raw_stream_status["sender_dropped_total"],
            "top_dropped_serials": raw_stream_status["top_dropped_serials"],
            "sample_media_ws_per_connection": sample_media_ws,
        }
        return {
            "phones": phones,
            "frames": frames,
            "slow_phones": slow_phones,
            "slow_send_ms": slow_send_ms,
            "shared_lock": shared_lock,
            "frame_interval_ms": frame_interval_ms,
            "sent_total": ws.sent_total,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "fast_seen": len(fast_lags),
            "fast_p50_ms": round(_percentile(fast_lags, 0.50), 3),
            "fast_p95_ms": round(_percentile(fast_lags, 0.95), 3),
            "fast_max_ms": round(max(fast_lags) if fast_lags else 0.0, 3),
            "slow_seen": len(slow_lags),
            "slow_p95_ms": round(_percentile(slow_lags, 0.95), 3),
            "telemetry": telemetry,
            "stream_status": stream_status,
        }
    finally:
        for task in sender_tasks:
            task.cancel()
        for task in sender_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark backend dispatch -> DeviceClient -> WS send path."
    )
    parser.add_argument("--phones", type=int, default=40)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--slow-phones", type=int, default=1)
    parser.add_argument("--slow-send-ms", type=float, default=25.0)
    parser.add_argument("--frame-interval-ms", type=float, default=5.0)
    parser.add_argument(
        "--mode",
        choices=("shared", "isolated"),
        default="isolated",
    )
    args = parser.parse_args()
    result = asyncio.run(
        _run(
            phones=args.phones,
            frames=args.frames,
            slow_phones=args.slow_phones,
            slow_send_ms=args.slow_send_ms,
            shared_lock=args.mode == "shared",
            frame_interval_ms=args.frame_interval_ms,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
