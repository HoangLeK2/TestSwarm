
from __future__ import annotations

import asyncio
import bisect
import logging
import math
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("relay.runtime")

_VIDEO_AGE_BUCKETS_MS = (
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1_000,
    2_000,
    5_000,
    10_000,
    30_000,
    60_000,
)


# ── JSON backend: orjson if available, stdlib fallback ───────────────────────
#
# orjson is a C extension that releases the GIL on dump and is 5–10x faster
# than the stdlib. We swap it in transparently so the rest of the code can
# stay on plain `dumps(...)`/`loads(...)` calls without caring which backend
# is in use.
#
# Callers may import `dumps` / `loads` from this module instead of `json` to
# get the speedup; the stdlib `json` module still works for legacy call sites.
try:
    import orjson as _orjson  # type: ignore[import-not-found]
    _HAS_ORJSON = True

    def dumps(obj: Any) -> str:
        """orjson-backed json.dumps replacement. Returns str for transport compat."""
        # orjson always returns bytes; decode once to str so consumers (gRPC
        # AgentMsg.meta, WebSocket text frames) can take it as-is.
        return _orjson.dumps(obj).decode("utf-8")

    def dumps_bytes(obj: Any) -> bytes:
        """orjson dumps without the decode round-trip (for byte transports)."""
        return _orjson.dumps(obj)

    def loads(data: Any) -> Any:
        return _orjson.loads(data)

except ImportError:  # pragma: no cover — orjson is in pyproject deps
    import json as _stdlib_json
    _HAS_ORJSON = False

    def dumps(obj: Any) -> str:
        return _stdlib_json.dumps(obj)

    def dumps_bytes(obj: Any) -> bytes:
        return _stdlib_json.dumps(obj).encode("utf-8")

    def loads(data: Any) -> Any:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        return _stdlib_json.loads(data)


def _env_int(name: str, default: int, *, lo: int = 1, hi: int = 1024) -> int:
    try:
        v = int(os.getenv(name, str(default)))
    except Exception:
        return default
    return max(lo, min(hi, v))


def _env_float(name: str, default: float, *, lo: float = 0.0, hi: float = 3600.0) -> float:
    try:
        v = float(os.getenv(name, str(default)))
    except Exception:
        return default
    return max(lo, min(hi, v))


# ── Tunables (env-overridable) ────────────────────────────────────────────────
#
# Pools are intentionally wider than the heavy ADB admission limit, but small
# enough that a start storm cannot create dozens of blocked subprocess workers.
# Scale phone count horizontally; tune only from measured queue/runtime stats.
#
ADB_POOL_SIZE       = _env_int("RELAY_ADB_POOL_SIZE", 12)
U2_POOL_SIZE        = _env_int("RELAY_U2_POOL_SIZE", 12)
SCRCPY_POOL_SIZE    = _env_int("RELAY_SCRCPY_POOL_SIZE", 3)
GENERIC_POOL_SIZE   = _env_int("RELAY_GENERIC_POOL_SIZE", 8)
# CPU pool: short, pure-Python work that blocks the event loop (json.dumps
# of large XML payloads, lxml parsing). Dedicated so a CPU spike does not
# starve adb/u2 throughput. Few threads — GIL means more is wasteful.
CPU_POOL_SIZE       = _env_int("RELAY_CPU_POOL_SIZE", 4)
# Payload size threshold: smaller dumps run on the loop (cheap), larger ones
# get offloaded to the CPU pool. Because we now serialise with orjson, which
# releases the GIL, offloading actually parallelises across threads — so the
# threshold is intentionally low (~8 KB) to push every non-trivial result onto
# the CPU pool. Bump it back up to ~256 KB if orjson is unavailable to avoid
# wasting executor round-trips on GIL-bound work.
JSON_OFFLOAD_BYTES  = _env_int("RELAY_JSON_OFFLOAD_BYTES", 8 * 1024, hi=16 * 1024 * 1024)

EXTRA_DATA_CONCURRENCY = _env_int("RELAY_EXTRA_DATA_CONCURRENCY", 4)
U2_BATCH_CONCURRENCY   = _env_int("RELAY_U2_BATCH_CONCURRENCY", 8)
U2_FLOW_CONCURRENCY    = _env_int("RELAY_U2_FLOW_CONCURRENCY", 8)

# FairSendQueue lane sizes. `per_device` is intentionally small — backpressure
# kicks in per phone so one chatty device cannot drown the others. `control`
# is generous because heartbeat/register messages must never drop.
SEND_PER_DEVICE_MAX = _env_int("RELAY_SEND_PER_DEVICE_MAX", 10)
SEND_VIDEO_PER_DEVICE_MAX = _env_int("RELAY_SEND_VIDEO_PER_DEVICE_MAX", 2)
SEND_CONTROL_MAX    = _env_int("RELAY_SEND_CONTROL_MAX", 128)

# How long bounded_put waits before declaring the send_queue dead. Long
# enough to absorb a transient gRPC flush, short enough that one stuck
# transport cannot block every coroutine for minutes.
SEND_PUT_TIMEOUT_S = _env_float("RELAY_SEND_PUT_TIMEOUT_S", 5.0, lo=0.5, hi=60.0)

LOOP_LAG_WARN_S    = _env_float("RELAY_LOOP_LAG_WARN_S", 2.0, lo=0.1, hi=60.0)
LOOP_LAG_PROBE_S   = _env_float("RELAY_LOOP_LAG_PROBE_S", 1.0, lo=0.1, hi=10.0)
STATS_INTERVAL_S   = _env_float("RELAY_STATS_INTERVAL_S", 60.0, lo=10.0, hi=3600.0)


# ── Bounded executor pools ────────────────────────────────────────────────────

@dataclass
class _Pools:
    adb:     Optional[ThreadPoolExecutor] = None
    u2:      Optional[ThreadPoolExecutor] = None
    scrcpy:  Optional[ThreadPoolExecutor] = None
    generic: Optional[ThreadPoolExecutor] = None
    cpu:     Optional[ThreadPoolExecutor] = None


_POOLS = _Pools()


def init_executors() -> None:
    """Idempotent: create named pools on first call."""
    if _POOLS.adb is None:
        _POOLS.adb = ThreadPoolExecutor(
            max_workers=ADB_POOL_SIZE, thread_name_prefix="relay-adb"
        )
    if _POOLS.u2 is None:
        _POOLS.u2 = ThreadPoolExecutor(
            max_workers=U2_POOL_SIZE, thread_name_prefix="relay-u2"
        )
    if _POOLS.scrcpy is None:
        _POOLS.scrcpy = ThreadPoolExecutor(
            max_workers=SCRCPY_POOL_SIZE, thread_name_prefix="relay-scrcpy"
        )
    if _POOLS.generic is None:
        _POOLS.generic = ThreadPoolExecutor(
            max_workers=GENERIC_POOL_SIZE, thread_name_prefix="relay-generic"
        )
    if _POOLS.cpu is None:
        _POOLS.cpu = ThreadPoolExecutor(
            max_workers=CPU_POOL_SIZE, thread_name_prefix="relay-cpu"
        )
    logger.info(
        "runtime: executors ready adb=%d u2=%d scrcpy=%d generic=%d cpu=%d json=%s",
        ADB_POOL_SIZE, U2_POOL_SIZE, SCRCPY_POOL_SIZE, GENERIC_POOL_SIZE, CPU_POOL_SIZE,
        "orjson" if _HAS_ORJSON else "stdlib",
    )


def shutdown_executors(wait: bool = False) -> None:
    """Shutdown all pools. `wait=False` returns immediately; threads finish in background."""
    for name in ("adb", "u2", "scrcpy", "generic", "cpu"):
        ex = getattr(_POOLS, name)
        if ex is not None:
            try:
                ex.shutdown(wait=wait, cancel_futures=True)
            except Exception:
                pass
            setattr(_POOLS, name, None)


def adb_executor() -> ThreadPoolExecutor:
    if _POOLS.adb is None:
        init_executors()
    assert _POOLS.adb is not None
    return _POOLS.adb


def u2_executor_pool() -> ThreadPoolExecutor:
    if _POOLS.u2 is None:
        init_executors()
    assert _POOLS.u2 is not None
    return _POOLS.u2


def scrcpy_executor() -> ThreadPoolExecutor:
    if _POOLS.scrcpy is None:
        init_executors()
    assert _POOLS.scrcpy is not None
    return _POOLS.scrcpy


def generic_executor() -> ThreadPoolExecutor:
    if _POOLS.generic is None:
        init_executors()
    assert _POOLS.generic is not None
    return _POOLS.generic


def cpu_executor() -> ThreadPoolExecutor:
    if _POOLS.cpu is None:
        init_executors()
    assert _POOLS.cpu is not None
    return _POOLS.cpu


# ── JSON serialisation helpers ────────────────────────────────────────────────
#
# Serialising a 1–8 MB dump_hierarchy / extra_data payload takes 50–500 ms of
# pure CPU on the event loop thread, which is *the* easiest way to make the
# relay look "frozen". `dumps_maybe_offload` runs small payloads inline
# (avoiding the executor round-trip) and offloads large ones to the CPU pool.
# With orjson the offloaded calls actually parallelise because the GIL is
# released around the C-level encoder.


def _measure(obj: Any) -> int:
    """Cheap upper-bound on JSON size: sum of all str/bytes values + 32 bytes."""
    total = 32
    stack = [obj]
    # Bounded scan — for nested payloads we count up to a few KB worth of
    # leaves; if a payload is small, we exit fast. The threshold check below
    # only needs an approximate answer.
    seen = 0
    while stack and seen < 200:
        seen += 1
        cur = stack.pop()
        if isinstance(cur, str):
            total += len(cur)
        elif isinstance(cur, (bytes, bytearray)):
            total += len(cur)
        elif isinstance(cur, dict):
            for v in cur.values():
                stack.append(v)
        elif isinstance(cur, (list, tuple)):
            stack.extend(cur)
        if total >= JSON_OFFLOAD_BYTES:
            return total
    return total


async def dumps_maybe_offload(payload: Any) -> str:
    """`dumps` on the loop for small payloads, CPU pool for large ones."""
    if _measure(payload) < JSON_OFFLOAD_BYTES:
        return dumps(payload)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(cpu_executor(), dumps, payload)


# ── Global semaphores ────────────────────────────────────────────────────────
#
# These are created lazily on the running loop so the module is import-safe
# from contexts without a loop (tests, REPL).

@dataclass
class _Semaphores:
    extra_data: Optional[asyncio.Semaphore] = None
    u2_batch:   Optional[asyncio.Semaphore] = None
    u2_flow:    Optional[asyncio.Semaphore] = None


_SEMS = _Semaphores()


def init_semaphores() -> None:
    if _SEMS.extra_data is None:
        _SEMS.extra_data = asyncio.Semaphore(EXTRA_DATA_CONCURRENCY)
    if _SEMS.u2_batch is None:
        _SEMS.u2_batch = asyncio.Semaphore(U2_BATCH_CONCURRENCY)
    if _SEMS.u2_flow is None:
        _SEMS.u2_flow = asyncio.Semaphore(U2_FLOW_CONCURRENCY)
    logger.info(
        "runtime: semaphores ready extra_data=%d u2_batch=%d u2_flow=%d",
        EXTRA_DATA_CONCURRENCY, U2_BATCH_CONCURRENCY, U2_FLOW_CONCURRENCY,
    )


def extra_data_sem() -> asyncio.Semaphore:
    if _SEMS.extra_data is None:
        init_semaphores()
    assert _SEMS.extra_data is not None
    return _SEMS.extra_data


def u2_batch_sem() -> asyncio.Semaphore:
    if _SEMS.u2_batch is None:
        init_semaphores()
    assert _SEMS.u2_batch is not None
    return _SEMS.u2_batch


def u2_flow_sem() -> asyncio.Semaphore:
    if _SEMS.u2_flow is None:
        init_semaphores()
    assert _SEMS.u2_flow is not None
    return _SEMS.u2_flow


# ── Bounded send_queue helpers ───────────────────────────────────────────────

@dataclass
class _DropCounter:
    sender_drops: int = 0       # bounded_put timeout (transport stuck)
    sender_overflow: int = 0    # bounded_put_nowait failed (lossy path)

    def snapshot_and_reset(self) -> tuple[int, int]:
        d, o = self.sender_drops, self.sender_overflow
        self.sender_drops = 0
        self.sender_overflow = 0
        return d, o


_DROPS = _DropCounter()


async def bounded_put(
    queue: Any,
    item: Any,
    *,
    serial: Optional[str] = None,
    timeout: Optional[float] = None,
    label: str = "send_queue",
) -> bool:
    """
    Put `item` into `queue` with a hard timeout. Returns True on success.

    On timeout we DROP the item, increment a counter, and log at WARNING
    so backpressure is visible. This is critical: without a timeout, a
    stuck transport (slow gRPC peer, dead WS) freezes every coroutine
    that needs to emit a result.

    `serial`: when `queue` is a FairSendQueue, tag the item to a specific
    phone's lane so backpressure is isolated per device. Plain
    `asyncio.Queue` callers can omit it; the arg is silently ignored.
    """
    t = SEND_PUT_TIMEOUT_S if timeout is None else timeout
    put_coro = (
        queue.put_with_serial(item, serial)
        if hasattr(queue, "put_with_serial")
        else queue.put(item)
    )
    try:
        await asyncio.wait_for(put_coro, timeout=t)
        return True
    except asyncio.TimeoutError:
        _DROPS.sender_drops += 1
        if _DROPS.sender_drops % 25 == 1:
            logger.warning(
                "%s put timeout (%.1fs) — transport stalled; dropped messages so far=%d qsize=%d serial=%s",
                label, t, _DROPS.sender_drops, queue.qsize(), serial or "-",
            )
        return False
    except Exception as exc:
        logger.debug("%s put error: %s", label, exc)
        return False


def bounded_put_nowait(
    queue: Any,
    item: Any,
    *,
    serial: Optional[str] = None,
    label: str = "send_queue",
) -> bool:
    """Lossy enqueue — return False on overflow without raising."""
    try:
        if hasattr(queue, "put_nowait_with_serial"):
            queue.put_nowait_with_serial(item, serial)
        else:
            queue.put_nowait(item)
        return True
    except asyncio.QueueFull:
        _DROPS.sender_overflow += 1
        if _DROPS.sender_overflow % 100 == 1:
            logger.warning(
                "%s overflow (lossy) — drops so far=%d qsize=%d serial=%s",
                label, _DROPS.sender_overflow, queue.qsize(), serial or "-",
            )
        return False


# ── FairSendQueue: per-device fairness + control plane priority ──────────────
#
# A single transport-bound queue (one phone with a chatty extra_data stream
# or a stuck IDR loop) was creating cross-device head-of-line blocking: a
# slow phone's 32 backed-up frames would starve every other phone's results
# until the sender drained them. FairSendQueue splits the single queue into:
#
#   • a high-priority "control" lane (heartbeat / register / unsolicited
#     ack) that is never starved by per-device backlog,
#   • one bounded sub-queue per known serial, drained round-robin so each
#     phone gets its share of transport bandwidth regardless of who else is
#     spamming results.
#
# Public API is drop-in compatible with `asyncio.Queue` (the sender task
# still does `await q.get()`). Producers tag items by calling
# `put_with_serial(item, serial)` / `put_nowait_with_serial(...)`; helpers
# like `bounded_put(..., serial=...)` do this automatically.

_MISSING = object()


class FairSendQueue:
    """Priority control + reliable + lossy-video lanes with device fairness."""

    def __init__(
        self,
        *,
        per_device_max: int = 16,
        control_max: int = 128,
        video_per_device_max: Optional[int] = None,
    ) -> None:
        self._per_device_max = max(1, per_device_max)
        self._video_per_device_max = max(
            2,
            video_per_device_max
            if video_per_device_max is not None
            else per_device_max,
        )
        self._control_max = max(1, control_max)
        self._control: asyncio.Queue = asyncio.Queue(maxsize=self._control_max)
        self._per_dev: dict[str, asyncio.Queue] = {}
        self._video_per_dev: dict[str, asyncio.Queue] = {}
        self._video_drops: dict[str, int] = {}
        self._video_evictions: dict[str, int] = {}
        self._video_suppressed: dict[str, int] = {}
        self._video_awaiting_keyframe: set[str] = set()
        self._video_resyncs = 0
        self._video_dequeued = 0
        self._video_age_samples = 0
        self._video_age_buckets = [0] * (len(_VIDEO_AGE_BUCKETS_MS) + 1)
        self._video_age_max_ms = 0
        self._video_handoff_samples = 0
        self._video_handoff_buckets = [0] * (len(_VIDEO_AGE_BUCKETS_MS) + 1)
        self._video_handoff_max_ms = 0
        self._reliable_items = 0
        self._video_items = 0
        # deque acts as the round-robin cursor — O(1) rotate(-1) advances it.
        self._rr: deque[str] = deque()
        self._video_rr: deque[str] = deque()
        # Alternate reliable/video when both are busy. Reliable goes first,
        # while video is guaranteed a turn under a continuous result stream.
        self._prefer_video = False
        # Wakes the (single) consumer when any sub-queue becomes non-empty.
        self._wake: asyncio.Event = asyncio.Event()

    # ── producer API ──────────────────────────────────────────────────────

    async def put(self, item: Any) -> None:
        """Untagged put — routed to the control lane (heartbeats, etc.)."""
        await self.put_with_serial(item, None)

    def put_nowait(self, item: Any) -> None:
        self.put_nowait_with_serial(item, None)

    async def put_with_serial(self, item: Any, serial: Optional[str]) -> None:
        q = self._lane_for(serial)
        await q.put(item)
        if serial:
            self._reliable_items += 1
        self._wake.set()

    def put_nowait_with_serial(self, item: Any, serial: Optional[str]) -> None:
        q = self._lane_for(serial)
        q.put_nowait(item)
        if serial:
            self._reliable_items += 1
        self._wake.set()

    def put_video_nowait(self, item: Any, serial: str) -> None:
        """Lossy video enqueue, isolated from reliable per-device results."""
        q = self._video_lane_for(serial)
        q.put_nowait(item)
        self._video_items += 1
        self._wake.set()

    def offer_video_nowait(
        self,
        item: Any,
        serial: str,
        *,
        is_config: bool,
        is_key: bool,
    ) -> bool:
        """Offer one H264 packet and return whether the producer should request IDR.

        Once a delta frame is dropped, later deltas are not decodable from the
        receiver's current reference chain. Suppress them until a keyframe is
        admitted instead of wasting transport capacity on corrupt output.
        """
        now_ns = time.monotonic_ns()
        received_ns = getattr(item, "received_ns", None)
        if isinstance(received_ns, int):
            self._record_video_handoff(
                max(0, math.ceil((now_ns - received_ns) / 1_000_000))
            )
        awaiting_keyframe = serial in self._video_awaiting_keyframe
        if awaiting_keyframe and not is_config and not is_key:
            self.record_video_drop(serial, suppressed=True)
            return False

        if hasattr(item, "enqueued_ns"):
            item.enqueued_ns = now_ns
        try:
            self.put_video_nowait(item, serial)
        except asyncio.QueueFull:
            if not is_config and not is_key:
                self.record_video_drop(serial)
                if awaiting_keyframe:
                    return False
                self._video_awaiting_keyframe.add(serial)
                return True
            if not self.evict_oldest_video(serial):
                return False
            try:
                self.put_video_nowait(item, serial)
            except asyncio.QueueFull:
                return False

        if is_key:
            if awaiting_keyframe:
                self._video_resyncs += 1
            self._video_awaiting_keyframe.discard(serial)
        return False

    def is_video_awaiting_keyframe(self, serial: str) -> bool:
        """Return whether a lane is suppressing deltas until decoder resync."""
        return serial in self._video_awaiting_keyframe

    def evict_oldest_video(self, serial: str) -> bool:
        """Evict one video frame only; never touches a reliable result lane."""
        q = self._video_per_dev.get(serial)
        if q is None:
            return False
        try:
            q.get_nowait()
            self._video_items -= 1
            self._video_evictions[serial] = (
                self._video_evictions.get(serial, 0) + 1
            )
            return True
        except asyncio.QueueEmpty:
            return False

    def record_video_drop(self, serial: str, *, suppressed: bool = False) -> None:
        """Record a dropped delta frame for periodic fleet diagnostics."""
        self._video_drops[serial] = self._video_drops.get(serial, 0) + 1
        if suppressed:
            self._video_suppressed[serial] = (
                self._video_suppressed.get(serial, 0) + 1
            )

    def video_stats_snapshot(self, *, reset: bool = False) -> dict[str, int]:
        """Aggregate video pressure without exposing phone identifiers in logs."""
        affected = (
            set(self._video_drops)
            | set(self._video_evictions)
            | set(self._video_suppressed)
            | self._video_awaiting_keyframe
        )
        stats = {
            "drops": sum(self._video_drops.values()),
            "evictions": sum(self._video_evictions.values()),
            "suppressed_until_keyframe": sum(self._video_suppressed.values()),
            "resyncs": self._video_resyncs,
            "awaiting_keyframe": len(self._video_awaiting_keyframe),
            "affected_serials": len(affected),
            "dequeued": self._video_dequeued,
            "queue_age_samples": self._video_age_samples,
            "queue_age_p50_ms": self._video_age_percentile(0.50),
            "queue_age_p95_ms": self._video_age_percentile(0.95),
            "queue_age_max_ms": self._video_age_max_ms,
            "handoff_age_samples": self._video_handoff_samples,
            "handoff_age_p50_ms": self._video_handoff_percentile(0.50),
            "handoff_age_p95_ms": self._video_handoff_percentile(0.95),
            "handoff_age_max_ms": self._video_handoff_max_ms,
        }
        if reset:
            self._video_drops.clear()
            self._video_evictions.clear()
            self._video_suppressed.clear()
            self._video_resyncs = 0
            self._video_dequeued = 0
            self._video_age_samples = 0
            self._video_age_buckets = [0] * (len(_VIDEO_AGE_BUCKETS_MS) + 1)
            self._video_age_max_ms = 0
            self._video_handoff_samples = 0
            self._video_handoff_buckets = [0] * (
                len(_VIDEO_AGE_BUCKETS_MS) + 1
            )
            self._video_handoff_max_ms = 0
        return stats

    def _record_video_handoff(self, age_ms: int) -> None:
        bucket = bisect.bisect_left(_VIDEO_AGE_BUCKETS_MS, age_ms)
        self._video_handoff_buckets[bucket] += 1
        self._video_handoff_samples += 1
        self._video_handoff_max_ms = max(self._video_handoff_max_ms, age_ms)

    def _record_video_dequeue(self, item: Any) -> None:
        self._video_dequeued += 1
        enqueued_ns = getattr(item, "enqueued_ns", None)
        if not isinstance(enqueued_ns, int) or enqueued_ns <= 0:
            return
        age_ms = max(0, math.ceil((time.monotonic_ns() - enqueued_ns) / 1_000_000))
        bucket = bisect.bisect_left(_VIDEO_AGE_BUCKETS_MS, age_ms)
        self._video_age_buckets[bucket] += 1
        self._video_age_samples += 1
        self._video_age_max_ms = max(self._video_age_max_ms, age_ms)

    def _video_age_percentile(self, percentile: float) -> int:
        return self._latency_percentile(
            self._video_age_buckets,
            self._video_age_samples,
            self._video_age_max_ms,
            percentile,
        )

    def _video_handoff_percentile(self, percentile: float) -> int:
        return self._latency_percentile(
            self._video_handoff_buckets,
            self._video_handoff_samples,
            self._video_handoff_max_ms,
            percentile,
        )

    @staticmethod
    def _latency_percentile(
        buckets: list[int],
        samples: int,
        max_ms: int,
        percentile: float,
    ) -> int:
        if samples <= 0:
            return 0
        target = max(1, math.ceil(samples * percentile))
        seen = 0
        for index, count in enumerate(buckets):
            seen += count
            if seen < target:
                continue
            if index < len(_VIDEO_AGE_BUCKETS_MS):
                return _VIDEO_AGE_BUCKETS_MS[index]
            return max_ms
        return max_ms

    # ── consumer API ──────────────────────────────────────────────────────

    async def get(self) -> Any:
        """Block until an item is available; respects control priority + RR."""
        while True:
            item = self._try_get_one()
            if item is not _MISSING:
                return item
            # Clear-then-check pattern: producers `set()` after a put, so if
            # one races between our check and clear, we'll see the item on
            # the second pass.
            self._wake.clear()
            item = self._try_get_one()
            if item is not _MISSING:
                self._wake.set()
                return item
            await self._wake.wait()

    def _try_get_one(self) -> Any:
        # 1) Control plane has absolute priority — never starved by frames.
        if not self._control.empty():
            return self._control.get_nowait()
        # 2) Alternate reliable and video service when both are continuously
        # busy. This keeps command results responsive without starving live
        # video for farms where every phone is streaming.
        reliable = (self._rr, self._per_dev, False)
        video = (self._video_rr, self._video_per_dev, True)
        lane_order = (video, reliable) if self._prefer_video else (reliable, video)
        for rr, lanes, is_video in lane_order:
            if is_video:
                if self._video_items <= 0:
                    continue
            elif self._reliable_items <= 0:
                continue
            item = self._try_get_round_robin(rr, lanes)
            if item is not _MISSING:
                if is_video:
                    self._video_items -= 1
                    self._record_video_dequeue(item)
                else:
                    self._reliable_items -= 1
                self._prefer_video = not is_video
                return item
        return _MISSING

    @staticmethod
    def _try_get_round_robin(
        rr: deque[str],
        lanes: dict[str, asyncio.Queue],
    ) -> Any:
        n = len(rr)
        for _ in range(n):
            # Rotate first so we don't keep favouring the same phone after a
            # quiet pass — the cursor always advances on every get attempt.
            rr.rotate(-1)
            serial = rr[0]
            q = lanes.get(serial)
            if q is not None and not q.empty():
                return q.get_nowait()
        return _MISSING

    # ── misc ──────────────────────────────────────────────────────────────

    def _lane_for(self, serial: Optional[str]) -> asyncio.Queue:
        if not serial:
            return self._control
        q = self._per_dev.get(serial)
        if q is None:
            q = asyncio.Queue(maxsize=self._per_device_max)
            self._per_dev[serial] = q
            self._rr.append(serial)
        return q

    def _video_lane_for(self, serial: str) -> asyncio.Queue:
        q = self._video_per_dev.get(serial)
        if q is None:
            q = asyncio.Queue(maxsize=self._video_per_device_max)
            self._video_per_dev[serial] = q
            self._video_rr.append(serial)
        return q

    def qsize(self) -> int:
        return self._control.qsize() + self._reliable_items + self._video_items

    @property
    def maxsize(self) -> int:
        reliable_capacity = self._per_device_max * max(1, len(self._per_dev))
        video_capacity = self._video_per_device_max * max(
            1,
            len(self._video_per_dev),
        )
        return self._control_max + reliable_capacity + video_capacity

    def drop_serial(self, serial: str) -> int:
        """Remove reliable + video lanes for a disconnected device."""
        n = self._drop_lane(serial, self._per_dev, self._rr)
        self._reliable_items = max(0, self._reliable_items - n)
        video_n = self._drop_lane(serial, self._video_per_dev, self._video_rr)
        self._video_items = max(0, self._video_items - video_n)
        self._video_awaiting_keyframe.discard(serial)
        return n + video_n

    @staticmethod
    def _drop_lane(
        serial: str,
        lanes: dict[str, asyncio.Queue],
        rr: deque[str],
    ) -> int:
        q = lanes.pop(serial, None)
        try:
            rr.remove(serial)
        except ValueError:
            pass
        if q is None:
            return 0
        n = q.qsize()
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break
        return n

    def snapshot(self) -> dict[str, int]:
        """Per-lane sizes — useful for diagnostics / stats logging."""
        snap: dict[str, int] = {"_control": self._control.qsize()}
        for serial, q in self._per_dev.items():
            snap[serial] = q.qsize()
        for serial, q in self._video_per_dev.items():
            snap[f"video:{serial}"] = q.qsize()
        return snap


# ── Task registry ─────────────────────────────────────────────────────────────

class TaskRegistry:
    """
    Tracks `asyncio.Task`s spawned by the agent so a transport reconnect
    or shutdown can cancel them.

    Without this, every `asyncio.create_task(handle_extra_data(...))` outlives
    its parent stream; after N reconnects the loop has hundreds of orphan
    tasks doing redundant work against stale send_queues.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def add(self, coro, *, name: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def active(self) -> int:
        return sum(1 for t in self._tasks if not t.done())

    async def cancel_all(self, *, timeout: float = 5.0) -> None:
        tasks = [t for t in self._tasks if not t.done()]
        if not tasks:
            return
        for t in tasks:
            t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            still = sum(1 for t in tasks if not t.done())
            logger.warning(
                "task_registry: %d tasks did not cancel within %.1fs", still, timeout,
            )


# ── Loop watchdog ────────────────────────────────────────────────────────────

class LoopWatchdog:
    """
    Detect event-loop stalls. Loops `await asyncio.sleep(probe)` and measures
    wall-clock drift; emits WARNING when drift > warn threshold.

    Loop stalls (>2s) almost always mean someone is doing CPU/blocking work
    on the loop thread. Catching them early prevents the cascade where
    heartbeats die, gRPC peer closes the stream, and the agent appears to
    freeze.
    """

    def __init__(
        self,
        *,
        probe_s: float = LOOP_LAG_PROBE_S,
        warn_s: float = LOOP_LAG_WARN_S,
    ) -> None:
        self._probe_s = probe_s
        self._warn_s = warn_s
        self._task: Optional[asyncio.Task] = None
        self._max_lag = 0.0
        self._warn_count = 0

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="relay-loop-watchdog")

    async def stop(self) -> None:
        t = self._task
        self._task = None
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    def stats(self) -> tuple[float, int]:
        m, c = self._max_lag, self._warn_count
        self._max_lag = 0.0
        return m, c

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            t0 = loop.time()
            try:
                await asyncio.sleep(self._probe_s)
            except asyncio.CancelledError:
                return
            lag = (loop.time() - t0) - self._probe_s
            if lag > self._max_lag:
                self._max_lag = lag
            if lag >= self._warn_s:
                self._warn_count += 1
                # Rate-limit: at most one log per stall episode (back-to-back
                # warnings get coalesced when the loop is still recovering).
                if self._warn_count % 5 == 1:
                    logger.warning(
                        "loop watchdog: event loop blocked for %.2fs (warn>=%.1fs, count=%d)",
                        lag, self._warn_s, self._warn_count,
                    )


# ── Periodic stats logger ────────────────────────────────────────────────────

@dataclass
class StatsSource:
    """Hooks the agent can register so the stats logger sees live counters."""
    name: str
    fn: Any  # Callable[[], dict[str, Any]]


_STATS_SOURCES: list[StatsSource] = []


def register_stats_source(name: str, fn) -> None:
    """Add a callable returning a dict of named counters for periodic logging."""
    _STATS_SOURCES.append(StatsSource(name=name, fn=fn))


class RuntimeStats:
    """Logs pool/semaphore/task/drop counters every STATS_INTERVAL_S."""

    def __init__(
        self,
        *,
        watchdog: Optional[LoopWatchdog] = None,
        task_registry: Optional[TaskRegistry] = None,
        interval_s: float = STATS_INTERVAL_S,
    ) -> None:
        self._wd = watchdog
        self._tr = task_registry
        self._interval = interval_s
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="relay-runtime-stats")

    async def stop(self) -> None:
        t = self._task
        self._task = None
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                return
            try:
                self._emit()
            except Exception as exc:
                logger.debug("runtime stats emit failed: %s", exc)

    def _emit(self) -> None:
        parts: list[str] = []

        def _pool_busy(ex: Optional[ThreadPoolExecutor]) -> tuple[int, int]:
            if ex is None:
                return 0, 0
            # _work_queue / _threads are internal but stable since 3.2.
            qsize = getattr(getattr(ex, "_work_queue", None), "qsize", lambda: 0)()
            threads = len(getattr(ex, "_threads", ()) or ())
            return threads, qsize

        for label, ex in (
            ("adb", _POOLS.adb),
            ("u2", _POOLS.u2),
            ("scrcpy", _POOLS.scrcpy),
            ("generic", _POOLS.generic),
        ):
            t, q = _pool_busy(ex)
            parts.append(f"{label}_t={t}/{ex._max_workers if ex else 0}")
            if q:
                parts.append(f"{label}_q={q}")

        for label, sem in (
            ("extra", _SEMS.extra_data),
            ("u2b", _SEMS.u2_batch),
            ("u2f", _SEMS.u2_flow),
        ):
            if sem is None:
                continue
            # asyncio.Semaphore exposes _value (available permits) since 3.4.
            free = getattr(sem, "_value", -1)
            parts.append(f"{label}_free={free}")

        if self._tr is not None:
            parts.append(f"tasks={self._tr.active()}")

        drops, overflow = _DROPS.snapshot_and_reset()
        if drops:
            parts.append(f"send_drops={drops}")
        if overflow:
            parts.append(f"send_overflow={overflow}")

        if self._wd is not None:
            max_lag, warn_count = self._wd.stats()
            if max_lag > 0:
                parts.append(f"loop_max_lag={max_lag:.2f}s")
            if warn_count:
                parts.append(f"loop_warns={warn_count}")

        # Allow external sources (e.g. u2 pool, scrcpy mgr) to publish counters.
        for src in _STATS_SOURCES:
            try:
                data = src.fn() or {}
            except Exception:
                continue
            for k, v in data.items():
                parts.append(f"{src.name}.{k}={v}")

        logger.info("runtime stats: %s", " ".join(parts))
