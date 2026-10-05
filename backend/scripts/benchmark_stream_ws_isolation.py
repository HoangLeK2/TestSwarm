from __future__ import annotations

import argparse
import asyncio
import json
import struct
import time
from dataclasses import dataclass, field

import web.ws as ws_module
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


def _h264_frame(serial: str, pts_us: int, *, is_key: bool = True) -> bytes:
    serial_b = serial.encode("utf-8")
    return (
        bytes([0x11, len(serial_b)])
        + serial_b
        + b"\x00\x01\x00\x01"
        + (b"\x01" if is_key else b"\x00")
        + struct.pack(">II", 0, pts_us)
        + b"payload"
    )


def _parse_frame(frame: bytes) -> tuple[str, int]:
    if not frame or frame[0] != 0x11:
        return "", -1
    serial_len = frame[1]
    serial = frame[2 : 2 + serial_len].decode("utf-8", errors="replace")
    pts_off = 7 + serial_len
    pts_us = struct.unpack(">II", frame[pts_off : pts_off + 8])[1]
    return serial, pts_us


def _queue_frame(q: asyncio.Queue[bytes], frame: bytes) -> bool:
    try:
        q.put_nowait(frame)
        return True
    except asyncio.QueueFull:
        # Mirror production behavior: drop stale delta frames, keep keyframes by
        # evicting the oldest queued item.
        serial_len = frame[1] if len(frame) > 1 else 0
        key_idx = 6 + serial_len
        is_key = 0 <= key_idx < len(frame) and frame[key_idx] == 0x01
        if not is_key:
            return False
        try:
            q.get_nowait()
            q.put_nowait(frame)
            return True
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            return False


@dataclass
class _FakeDevice:
    serial: str
    _q: asyncio.Queue[bytes] | None = None

    def get_stream_bootstrap(self, *_args, **_kwargs):
        return None, None

    def subscribe_frames(self, q: asyncio.Queue, **_kwargs):
        self._q = q
        return None, None

    def unsubscribe_frames(self, q: asyncio.Queue) -> None:
        if self._q is q:
            self._q = None


class _FakeManager:
    def __init__(self, devices: list[_FakeDevice]) -> None:
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
        serial, pts_us = _parse_frame(frame)
        if serial in self.slow_serials:
            await asyncio.sleep(self.slow_send_ms / 1000.0)
        now = time.perf_counter()
        put_ts = self.put_times.get((serial, pts_us))
        if put_ts is not None:
            self.lags_by_serial.setdefault(serial, []).append((now - put_ts) * 1000.0)
        self.sent_total += 1


async def _run(
    *,
    phones: int,
    frames: int,
    slow_phones: int,
    slow_send_ms: float,
    shared_lock: bool,
    lock_wait_ms: float,
    frame_interval_ms: float,
) -> dict:
    previous_lock_wait = ws_module.STREAM_WS_LOCK_WAIT_MS
    ws_module.STREAM_WS_LOCK_WAIT_MS = lock_wait_ms
    try:
        devices = [_FakeDevice(f"SN{i:04d}") for i in range(phones)]
        slow_serials = {device.serial for device in devices[:slow_phones]}
        put_times: dict[tuple[str, int], float] = {}
        ws = _TimedWebSocket(
            slow_serials=slow_serials,
            slow_send_ms=slow_send_ms,
            put_times=put_times,
        )
        ws_manager = WebSocketManager(_FakeManager(devices), db_enabled=False, read_only=False)
        one_lock = asyncio.Lock()
        tasks: list[asyncio.Task] = []
        producer_drops = 0
        for device in devices:
            lock = one_lock if shared_lock else asyncio.Lock()
            tasks.append(asyncio.create_task(ws_manager._device_sender(ws, device, lock)))

        try:
            for _ in range(100):
                if all(device._q is not None for device in devices):
                    break
                await asyncio.sleep(0.005)
            if not all(device._q is not None for device in devices):
                raise RuntimeError("device sender queues were not ready")

            started = time.perf_counter()
            for seq in range(frames):
                for device in devices:
                    put_times[(device.serial, seq)] = time.perf_counter()
                    frame = _h264_frame(device.serial, seq, is_key=seq % 15 == 0)
                    if not _queue_frame(device._q, frame):
                        producer_drops += 1
                await asyncio.sleep(frame_interval_ms / 1000.0)

            deadline = time.perf_counter() + 3.0
            while time.perf_counter() < deadline:
                expected_fast = (phones - slow_phones) * frames
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
            return {
                "phones": phones,
                "frames": frames,
                "slow_phones": slow_phones,
                "slow_send_ms": slow_send_ms,
                "shared_lock": shared_lock,
                "lock_wait_ms": lock_wait_ms,
                "frame_interval_ms": frame_interval_ms,
                "sent_total": ws.sent_total,
                "producer_drops": producer_drops,
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "fast_seen": len(fast_lags),
                "fast_p50_ms": round(_percentile(fast_lags, 0.50), 3),
                "fast_p95_ms": round(_percentile(fast_lags, 0.95), 3),
                "fast_max_ms": round(max(fast_lags) if fast_lags else 0.0, 3),
                "slow_seen": len(slow_lags),
                "slow_p95_ms": round(_percentile(slow_lags, 0.95), 3),
            }
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    finally:
        ws_module.STREAM_WS_LOCK_WAIT_MS = previous_lock_wait


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark stream WS latency isolation.")
    parser.add_argument("--phones", type=int, default=40)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--slow-phones", type=int, default=1)
    parser.add_argument("--slow-send-ms", type=float, default=25.0)
    parser.add_argument("--lock-wait-ms", type=float, default=8.0)
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
            lock_wait_ms=args.lock_wait_ms,
            frame_interval_ms=args.frame_interval_ms,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
