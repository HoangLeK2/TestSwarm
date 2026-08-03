"""Production-shaped synthetic validation for agent stream SLOs.

The harness replaces physical phones and the network peer. Packet preparation,
cross-thread handoff, fair queueing, protobuf serialization, and receiver-side
protobuf decoding use the production modules. It measures the agent transport
seam, not USB capture, network transit, backend forwarding, or browser decode.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from dataclasses import dataclass, replace

from .grpc_client import agent_message_from_item
from .grpc_gen import relay_pb2
from .runtime import FairSendQueue, MultiStreamSendQueue
from .scrcpy_relay import enqueue_video_packet, prepare_video_packet
from .video_packet import VideoPacket


@dataclass(frozen=True, slots=True)
class StreamSloThresholds:
    """Acceptance thresholds for one synthetic fleet run."""

    handoff_p95_ms: float = 10.0
    queue_age_p95_ms: float = 50.0
    idr_recovery_p95_ms: float = 300.0


@dataclass(frozen=True, slots=True)
class MockFleetConfig:
    """Workload emitted by independent mock phone threads."""

    phones: int
    duration_s: float = 1.0
    fps: float = 12.0
    payload_bytes: int = 50_000
    idr_response_ms: float = 100.0
    command_interval_s: float = 0.25
    consumer_delay_ms: float = 0.0
    reliable_per_device_max: int = 16
    video_per_device_max: int = 2
    visible_phones: int | None = None
    video_shards: int = 8
    noisy_phone_index: int | None = None
    noisy_fps_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.phones <= 0:
            raise ValueError("phones must be positive")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.payload_bytes <= 0:
            raise ValueError("payload_bytes must be positive")
        if self.idr_response_ms < 0:
            raise ValueError("idr_response_ms cannot be negative")
        if self.command_interval_s <= 0:
            raise ValueError("command_interval_s must be positive")
        if self.reliable_per_device_max <= 0:
            raise ValueError("reliable_per_device_max must be positive")
        if self.video_per_device_max < 2:
            raise ValueError("video_per_device_max must be at least two")
        if self.visible_phones is not None and not (
            1 <= self.visible_phones <= self.phones
        ):
            raise ValueError("visible_phones must be between one and phones")
        if self.video_shards < 0:
            raise ValueError("video_shards cannot be negative")
        if self.noisy_phone_index is not None and not (
            0 <= self.noisy_phone_index < self.phones
        ):
            raise ValueError("noisy_phone_index must identify one mock phone")
        if self.noisy_fps_multiplier < 1:
            raise ValueError("noisy_fps_multiplier must be at least one")


@dataclass(frozen=True, slots=True)
class MockFleetReport:
    """Observed agent transport-seam metrics and their SLO verdicts.

    Command loss compares issued mock command IDs with command-result IDs
    decoded by the mock transport receiver. IDR recovery spans the first
    queue drop/IDR request through admission of the replacement keyframe.
    """

    measurement_scope: str
    phones: int
    visible_phones: int
    video_shards: int
    elapsed_s: float
    generated_video_packets: int
    delivered_video_packets: int
    commands_sent: int
    commands_delivered: int
    command_loss: int
    handoff_p95_ms: float
    queue_age_p95_ms: float
    idr_recovery_p95_ms: float
    idr_recoveries: int
    protobuf_bytes: int
    max_queue_size: int
    per_phone_handoff_p95_ms: dict[str, float]
    per_phone_queue_age_p95_ms: dict[str, float]
    thresholds: StreamSloThresholds

    @property
    def slo_pass(self) -> dict[str, bool]:
        return {
            "command_loss": self.command_loss == 0,
            "handoff_p95": (
                self.handoff_p95_ms <= self.thresholds.handoff_p95_ms
            ),
            "idr_recovery_p95": (
                self.idr_recoveries == self.visible_phones
                and self.idr_recovery_p95_ms
                <= self.thresholds.idr_recovery_p95_ms
            ),
            "queue_age_p95": (
                self.queue_age_p95_ms <= self.thresholds.queue_age_p95_ms
            ),
        }

    @property
    def passed(self) -> bool:
        return all(self.slo_pass.values())


@dataclass(frozen=True, slots=True)
class MockIsolationReport:
    """Difference observed on normal phones when one phone becomes noisy."""

    baseline: MockFleetReport
    noisy_run: MockFleetReport
    noisy_serial: str
    max_normal_phone_handoff_p95_delta_ms: float
    max_normal_phone_queue_age_p95_delta_ms: float
    max_normal_phone_p95_delta_ms: float
    allowed_p95_delta_ms: float
    normal_phones_within_slo: bool

    @property
    def passed(self) -> bool:
        return (
            self.baseline.passed
            and self.noisy_run.passed
            and self.normal_phones_within_slo
            and self.max_normal_phone_p95_delta_ms
            <= self.allowed_p95_delta_ms
        )


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return math.inf
    ordered = sorted(samples)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[index], 3)


async def run_mock_fleet(
    config: MockFleetConfig,
    thresholds: StreamSloThresholds | None = None,
) -> MockFleetReport:
    """Measure the production stream seam with mock phone producers."""

    applied_thresholds = thresholds or StreamSloThresholds()
    loop = asyncio.get_running_loop()
    if config.video_shards > 0:
        queue: FairSendQueue | MultiStreamSendQueue = MultiStreamSendQueue(
            video_shards=config.video_shards,
            per_device_max=config.reliable_per_device_max,
            video_per_device_max=config.video_per_device_max,
        )
    else:
        queue = FairSendQueue(
            per_device_max=config.reliable_per_device_max,
            video_per_device_max=config.video_per_device_max,
        )
    serials = [f"mock-phone-{index:03d}" for index in range(config.phones)]
    visible_count = config.visible_phones or config.phones
    video_serials = set(serials[:visible_count])
    recovery_events = {serial: threading.Event() for serial in serials}
    recovery_started_ns: dict[str, int] = {}
    idr_recovery_ms: list[float] = []
    handoff_ms: list[float] = []
    queue_age_ms: list[float] = []
    handoff_ms_by_serial = {serial: [] for serial in video_serials}
    queue_age_ms_by_serial = {serial: [] for serial in video_serials}
    command_ids: set[str] = set()
    delivered_command_ids: set[str] = set()
    producer_errors: list[BaseException] = []
    producers_done = asyncio.Event()
    counter_lock = threading.Lock()
    producer_indexes = set(range(visible_count))
    if config.noisy_phone_index is not None:
        producer_indexes.add(config.noisy_phone_index)
    producer_indexes = {
        index
        for index in producer_indexes
        if 0 <= index < config.phones
    }
    remaining = len(producer_indexes)
    generated_video_packets = 0
    max_queue_size = 0
    payload = b"x" * config.payload_bytes

    def on_drop(serial: str) -> None:
        if serial in recovery_started_ns:
            return
        recovery_started_ns[serial] = time.monotonic_ns()
        recovery_events[serial].set()

    def on_resync(serial: str) -> None:
        started_ns = recovery_started_ns.pop(serial, None)
        if started_ns is None:
            return
        idr_recovery_ms.append(
            (time.monotonic_ns() - started_ns) / 1_000_000
        )
        recovery_events[serial].clear()

    def enqueue_packet(packet: VideoPacket) -> None:
        nonlocal max_queue_size
        enqueue_video_packet(
            queue,
            packet,
            lambda: on_drop(packet.serial),
            lambda: on_resync(packet.serial),
        )
        max_queue_size = max(max_queue_size, queue.qsize())

    def enqueue_recovery_burst(packets: tuple[VideoPacket, ...]) -> None:
        for packet in packets:
            enqueue_packet(packet)

    async def enqueue_command(serial: str, command_id: str) -> None:
        nonlocal max_queue_size
        queued_ns = time.monotonic_ns()
        item = json.dumps(
            {
                "kind": "mock_command_result",
                "command_id": command_id,
                "serial": serial,
                "queued_ns": queued_ns,
            },
            separators=(",", ":"),
        )
        await queue.put_with_serial(item, serial)
        max_queue_size = max(max_queue_size, queue.qsize())

    def mark_producer_done() -> None:
        nonlocal remaining
        remaining -= 1
        if remaining == 0:
            producers_done.set()

    def make_packet(
        serial: str,
        frame_index: int,
        *,
        is_key: bool = False,
        suppress_deltas: bool = False,
    ) -> VideoPacket | None:
        nal_type = 0x65 if is_key else 0x61
        return prepare_video_packet(
            serial=serial,
            annexb=b"\x00\x00\x00\x01" + bytes([nal_type]) + payload,
            is_config=False,
            pts_us=frame_index,
            received_ns=time.monotonic_ns(),
            suppress_deltas=suppress_deltas,
        )

    def produce(serial: str, phone_index: int) -> None:
        nonlocal generated_video_packets
        try:
            emits_video = serial in video_serials
            base_tick_hz = (
                config.fps
                if emits_video
                else max(1.0, 1.0 / config.command_interval_s)
            )
            effective_fps = base_tick_hz
            if phone_index == config.noisy_phone_index:
                effective_fps *= config.noisy_fps_multiplier
            interval_s = 1.0 / effective_fps
            frames = max(
                4 if emits_video else 1,
                math.ceil(config.duration_s * effective_fps),
            )
            recovery_at = max(1, frames // 3)
            command_every = max(
                1,
                round(config.command_interval_s * base_tick_hz),
            )
            phase_s = (phone_index / config.phones) * min(interval_s, 0.05)
            next_frame_at = time.perf_counter() + phase_s

            for frame_index in range(frames):
                remaining_sleep = next_frame_at - time.perf_counter()
                if remaining_sleep > 0:
                    time.sleep(remaining_sleep)
                next_frame_at += interval_s

                if frame_index % command_every == 0:
                    command_id = f"{serial}:{frame_index}"
                    with counter_lock:
                        command_ids.add(command_id)
                    future = asyncio.run_coroutine_threadsafe(
                        enqueue_command(serial, command_id),
                        loop,
                    )
                    future.result(timeout=2.0)

                if not emits_video:
                    continue

                if frame_index == recovery_at:
                    burst = tuple(
                        packet
                        for offset in range(config.video_per_device_max + 1)
                        if (
                            packet := make_packet(
                                serial,
                                frame_index * 100 + offset,
                            )
                        )
                        is not None
                    )
                    with counter_lock:
                        generated_video_packets += len(burst)
                    loop.call_soon_threadsafe(enqueue_recovery_burst, burst)
                    if not recovery_events[serial].wait(timeout=2.0):
                        raise TimeoutError(
                            f"{serial} did not enter IDR recovery"
                        )
                    time.sleep(config.idr_response_ms / 1_000)
                    idr = make_packet(serial, frame_index, is_key=True)
                    if idr is not None:
                        with counter_lock:
                            generated_video_packets += 1
                        loop.call_soon_threadsafe(enqueue_packet, idr)
                    continue

                packet = make_packet(
                    serial,
                    frame_index,
                    suppress_deltas=recovery_events[serial].is_set(),
                )
                if packet is not None:
                    with counter_lock:
                        generated_video_packets += 1
                    loop.call_soon_threadsafe(enqueue_packet, packet)
        # Thread boundary: preserve every producer failure for the async caller.
        except Exception as exc:  # noqa: BLE001
            with counter_lock:
                producer_errors.append(exc)
        finally:
            loop.call_soon_threadsafe(mark_producer_done)

    threads = [
        threading.Thread(
            target=produce,
            args=(serial, index),
            name=f"stream-slo-{serial}",
            daemon=True,
        )
        for index, serial in enumerate(serials)
        if index in producer_indexes
    ]
    started = time.perf_counter()
    for thread in threads:
        thread.start()

    protobuf_bytes = 0
    delay_s = config.consumer_delay_ms / 1_000
    delivered_video_packets = 0

    async def consume_queue(
        source_queue: FairSendQueue | MultiStreamSendQueue,
    ) -> None:
        nonlocal protobuf_bytes, delivered_video_packets
        while not producers_done.is_set() or source_queue.qsize() > 0:
            try:
                item = await asyncio.wait_for(source_queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            dequeued_ns = time.monotonic_ns()
            message = agent_message_from_item(item, relay_pb2)
            if message is None:
                raise RuntimeError("mock stream item could not be serialized")
            wire_bytes = message.SerializeToString()
            protobuf_bytes += len(wire_bytes)
            received_message = relay_pb2.AgentMsg.FromString(wire_bytes)

            if isinstance(item, VideoPacket):
                delivered_video_packets += 1
                packet_handoff_ms = max(
                    0.0,
                    (item.enqueued_ns - item.received_ns) / 1_000_000,
                )
                packet_queue_age_ms = max(
                    0.0,
                    (dequeued_ns - item.enqueued_ns) / 1_000_000,
                )
                handoff_ms.append(packet_handoff_ms)
                queue_age_ms.append(packet_queue_age_ms)
                handoff_ms_by_serial[item.serial].append(packet_handoff_ms)
                queue_age_ms_by_serial[item.serial].append(packet_queue_age_ms)
            elif isinstance(item, str):
                meta = json.loads(received_message.meta)
                if meta.get("kind") == "mock_command_result":
                    delivered_command_ids.add(str(meta["command_id"]))

            if delay_s > 0:
                await asyncio.sleep(delay_s)

    if isinstance(queue, MultiStreamSendQueue):
        consumers = [
            asyncio.create_task(consume_queue(queue), name="mock-reliable-consumer"),
            *[
                asyncio.create_task(
                    consume_queue(queue.video_shard_queue(index)),
                    name=f"mock-video-shard-consumer-{index}",
                )
                for index in range(queue.video_shard_count())
            ],
        ]
        await asyncio.gather(*consumers)
    else:
        await consume_queue(queue)

    for thread in threads:
        thread.join(timeout=0.1)
    if producer_errors:
        raise RuntimeError("mock phone producer failed") from producer_errors[0]

    elapsed_s = time.perf_counter() - started
    return MockFleetReport(
        measurement_scope="agent_boot_transport_seam",
        phones=config.phones,
        visible_phones=visible_count,
        video_shards=config.video_shards,
        elapsed_s=round(elapsed_s, 3),
        generated_video_packets=generated_video_packets,
        delivered_video_packets=delivered_video_packets,
        commands_sent=len(command_ids),
        commands_delivered=len(delivered_command_ids),
        command_loss=len(command_ids - delivered_command_ids),
        handoff_p95_ms=_percentile(handoff_ms, 0.95),
        queue_age_p95_ms=_percentile(queue_age_ms, 0.95),
        idr_recovery_p95_ms=_percentile(idr_recovery_ms, 0.95),
        idr_recoveries=len(idr_recovery_ms),
        protobuf_bytes=protobuf_bytes,
        max_queue_size=max_queue_size,
        per_phone_handoff_p95_ms={
            serial: _percentile(samples, 0.95)
            for serial, samples in handoff_ms_by_serial.items()
            if samples
        },
        per_phone_queue_age_p95_ms={
            serial: _percentile(samples, 0.95)
            for serial, samples in queue_age_ms_by_serial.items()
            if samples
        },
        thresholds=applied_thresholds,
    )


async def run_mock_isolation_probe(
    config: MockFleetConfig,
    *,
    noisy_fps_multiplier: float = 8.0,
    max_normal_phone_p95_delta_ms: float = 5.0,
    thresholds: StreamSloThresholds | None = None,
) -> MockIsolationReport:
    """Compare normal-phone latency with and without one noisy phone.

    The delta budget absorbs OS thread-scheduling jitter between two separate
    real-time runs. Absolute handoff and queue SLOs still apply to both runs.
    """

    if config.phones < 2:
        raise ValueError("isolation probe requires at least two phones")
    if max_normal_phone_p95_delta_ms < 0:
        raise ValueError("max_normal_phone_p95_delta_ms cannot be negative")
    applied_thresholds = thresholds or StreamSloThresholds()
    baseline_config = replace(
        config,
        noisy_phone_index=None,
        noisy_fps_multiplier=1.0,
    )
    if config.visible_phones is not None and config.visible_phones < config.phones:
        noisy_index = config.visible_phones
    else:
        noisy_index = 0
    noisy_config = replace(
        config,
        noisy_phone_index=noisy_index,
        noisy_fps_multiplier=noisy_fps_multiplier,
    )
    baseline = await run_mock_fleet(baseline_config, applied_thresholds)
    noisy_run = await run_mock_fleet(noisy_config, applied_thresholds)
    noisy_serial = f"mock-phone-{noisy_index:03d}"
    normal_serials = (
        set(baseline.per_phone_queue_age_p95_ms)
        & set(noisy_run.per_phone_queue_age_p95_ms)
    ) - {noisy_serial}

    handoff_deltas = [
        max(
            0.0,
            noisy_run.per_phone_handoff_p95_ms[serial]
            - baseline.per_phone_handoff_p95_ms[serial],
        )
        for serial in normal_serials
    ]
    queue_deltas = [
        max(
            0.0,
            noisy_run.per_phone_queue_age_p95_ms[serial]
            - baseline.per_phone_queue_age_p95_ms[serial],
        )
        for serial in normal_serials
    ]
    max_handoff_delta = round(max(handoff_deltas, default=math.inf), 3)
    max_queue_delta = round(max(queue_deltas, default=math.inf), 3)
    normal_phones_within_slo = all(
        noisy_run.per_phone_handoff_p95_ms[serial]
        <= applied_thresholds.handoff_p95_ms
        and noisy_run.per_phone_queue_age_p95_ms[serial]
        <= applied_thresholds.queue_age_p95_ms
        for serial in normal_serials
    )
    return MockIsolationReport(
        baseline=baseline,
        noisy_run=noisy_run,
        noisy_serial=noisy_serial,
        max_normal_phone_handoff_p95_delta_ms=max_handoff_delta,
        max_normal_phone_queue_age_p95_delta_ms=max_queue_delta,
        max_normal_phone_p95_delta_ms=max(
            max_handoff_delta,
            max_queue_delta,
        ),
        allowed_p95_delta_ms=max_normal_phone_p95_delta_ms,
        normal_phones_within_slo=normal_phones_within_slo,
    )
