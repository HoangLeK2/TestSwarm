"""Bounded, per-phone admission for commands sent to the host ADB server."""

from __future__ import annotations

import contextlib
import itertools
import math
import os
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


class AdbLane(IntEnum):
    """Lower values are admitted first."""

    INTERACTIVE = 0
    STARTUP = 1
    DEFAULT = 2
    MAINTENANCE = 3

    @property
    def heavy(self) -> bool:
        return self in (AdbLane.STARTUP, AdbLane.MAINTENANCE)


def classify_adb_command(
    args: tuple[str, ...],
    *,
    default: AdbLane = AdbLane.DEFAULT,
) -> AdbLane:
    """Classify common ADB commands without making callers know scheduler policy."""
    if not args:
        return default
    command = str(args[0]).strip().lower()
    joined = " ".join(str(arg) for arg in args[1:]).strip().lower()

    if command == "shell" and joined.startswith(("input ", "cmd input ")):
        return AdbLane.INTERACTIVE
    if command in {"push", "install", "install-multiple", "sync", "uninstall"}:
        return AdbLane.MAINTENANCE
    if command == "shell" and any(
        marker in joined
        for marker in (
            "mkdir -p /data/local/tmp",
            "pm install",
            "chmod ",
            " chmod ",
            "mv -f /data/local/tmp",
        )
    ):
        return AdbLane.MAINTENANCE
    if command in {"forward", "reverse"}:
        return AdbLane.STARTUP
    return default


@dataclass(frozen=True, slots=True)
class _Ticket:
    lane: AdbLane
    sequence: int
    serial: str
    enqueued_at: float


class AdbAdmissionController:
    """Keep ADB bounded globally while isolating work for each phone."""

    def __init__(
        self,
        *,
        max_concurrency: int,
        reserved_interactive: int,
        reserved_startup: int = 0,
        max_heavy: int,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._max_concurrency = max_concurrency
        self._reserved_interactive = min(
            max(0, reserved_interactive),
            max_concurrency - 1,
        )
        self._max_heavy = min(max(1, max_heavy), max_concurrency)
        self._reserved_startup = min(
            max(0, reserved_startup),
            max(0, self._max_heavy - 1),
        )
        self._condition = threading.Condition()
        self._sequence = itertools.count()
        self._waiters: list[_Ticket] = []
        self._active_serials: set[str] = set()
        self._active = 0
        self._active_noninteractive = 0
        self._active_heavy = 0
        self._active_startup = 0
        self._max_active = 0
        self._completed = 0
        self._queue_wait_ms: deque[int] = deque(maxlen=4096)

    @contextlib.contextmanager
    def admit(self, *, serial: str | None, lane: AdbLane) -> Iterator[None]:
        lane = AdbLane(lane)
        serial_key = str(serial or "__adb_host__")
        ticket = _Ticket(
            lane=lane,
            sequence=next(self._sequence),
            serial=serial_key,
            enqueued_at=time.monotonic(),
        )
        with self._condition:
            self._waiters.append(ticket)
            while not self._can_admit(ticket):
                self._condition.wait()
            self._waiters.remove(ticket)
            self._active_serials.add(serial_key)
            self._active += 1
            if lane != AdbLane.INTERACTIVE:
                self._active_noninteractive += 1
            if lane.heavy:
                self._active_heavy += 1
            if lane == AdbLane.STARTUP:
                self._active_startup += 1
            self._max_active = max(self._max_active, self._active)
            self._queue_wait_ms.append(
                max(0, round((time.monotonic() - ticket.enqueued_at) * 1_000))
            )

        try:
            yield
        finally:
            with self._condition:
                self._active_serials.discard(serial_key)
                self._active -= 1
                if lane != AdbLane.INTERACTIVE:
                    self._active_noninteractive -= 1
                if lane.heavy:
                    self._active_heavy -= 1
                if lane == AdbLane.STARTUP:
                    self._active_startup -= 1
                self._completed += 1
                self._condition.notify_all()

    def _can_admit(self, ticket: _Ticket) -> bool:
        if ticket.serial in self._active_serials:
            return False
        if not self._is_serial_head(ticket):
            return False
        if not self._fits_capacity(ticket):
            return False

        runnable = (
            candidate
            for candidate in self._waiters
            if self._is_serial_head(candidate)
            and candidate.serial not in self._active_serials
            and self._fits_capacity(candidate)
        )
        first = min(
            runnable,
            key=(
                (lambda candidate: (candidate.sequence,))
                if self._max_concurrency == 1
                else (lambda candidate: (candidate.lane, candidate.sequence))
            ),
            default=None,
        )
        return first is ticket

    def _fits_capacity(self, ticket: _Ticket) -> bool:
        if self._active >= self._max_concurrency:
            return False
        if ticket.lane.heavy and self._active_heavy >= self._max_heavy:
            return False
        if (
            ticket.lane == AdbLane.MAINTENANCE
            and self._reserved_startup > 0
            and self._has_waiting_lane(lane=AdbLane.STARTUP)
        ):
            active_maintenance = self._active_heavy - self._active_startup
            if active_maintenance >= self._max_heavy - self._reserved_startup:
                return False
        if self._max_concurrency == 1:
            return True

        active_interactive = self._active - self._active_noninteractive
        if ticket.lane == AdbLane.INTERACTIVE:
            return not (
                self._has_waiting_interactive(False)
                and active_interactive >= self._max_concurrency - 1
            )
        return not (
            self._has_waiting_interactive(True)
            and self._active_noninteractive
            >= self._max_concurrency - self._reserved_interactive
        )

    def _has_waiting_interactive(self, interactive: bool) -> bool:
        return any(
            self._is_serial_head(candidate)
            and candidate.serial not in self._active_serials
            and (candidate.lane == AdbLane.INTERACTIVE) is interactive
            for candidate in self._waiters
        )

    def _has_waiting_lane(self, *, lane: AdbLane) -> bool:
        return any(
            self._is_serial_head(candidate)
            and candidate.serial not in self._active_serials
            and candidate.lane == lane
            for candidate in self._waiters
        )

    def _is_serial_head(self, ticket: _Ticket) -> bool:
        return not any(
            candidate.serial == ticket.serial
            and candidate.sequence < ticket.sequence
            for candidate in self._waiters
        )

    def snapshot(self, *, reset: bool = False) -> dict[str, int]:
        """Return bounded-cardinality metrics for runtime logs."""
        with self._condition:
            ordered = sorted(self._queue_wait_ms)
            sample_count = len(ordered)

            def percentile(ratio: float) -> int:
                if not ordered:
                    return 0
                index = min(
                    sample_count - 1,
                    max(0, math.ceil(sample_count * ratio) - 1),
                )
                return ordered[index]

            result = {
                "active": self._active,
                "active_heavy": self._active_heavy,
                "active_startup": self._active_startup,
                "waiting": len(self._waiters),
                "completed": self._completed,
                "max_active": self._max_active,
                "queue_wait_samples": sample_count,
                "queue_wait_p50_ms": percentile(0.50),
                "queue_wait_p95_ms": percentile(0.95),
                "queue_wait_max_ms": max(ordered, default=0),
            }
            if reset:
                self._completed = 0
                self._max_active = self._active
                self._queue_wait_ms.clear()
            return result


_CONTROLLER = AdbAdmissionController(
    max_concurrency=_env_int(
        "RELAY_ADB_COMMAND_CONCURRENCY",
        12,
        minimum=1,
        maximum=32,
    ),
    reserved_interactive=_env_int(
        "RELAY_ADB_INTERACTIVE_RESERVED",
        2,
        minimum=0,
        maximum=8,
    ),
    reserved_startup=_env_int(
        "RELAY_ADB_STARTUP_RESERVED",
        2,
        minimum=0,
        maximum=8,
    ),
    max_heavy=_env_int("RELAY_ADB_HEAVY_CONCURRENCY", 3, minimum=1, maximum=6),
)


def adb_admission(
    *,
    serial: str | None,
    lane: AdbLane,
) -> contextlib.AbstractContextManager[None]:
    """Use the process-wide ADB admission controller."""
    return _CONTROLLER.admit(serial=serial, lane=lane)


def adb_admission_stats(*, reset: bool = False) -> dict[str, int]:
    """Runtime stats for the process-wide controller."""
    return _CONTROLLER.snapshot(reset=reset)
