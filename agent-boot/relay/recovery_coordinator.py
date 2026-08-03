"""Bounded/coalesced admission for slow per-device recovery work."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

RecoveryResult = tuple[str, int]


@dataclass(slots=True)
class _BreakerState:
    failures: int = 0
    opened_until: float = 0.0


class RecoveryCoordinator:
    """Coalesce duplicate recovery commands and isolate failing phones.

    ADB recovery storms usually arrive as repeated restart/bootstrap requests
    for the same serial while the first repair is still running or repeatedly
    failing. This coordinator admits one in-flight operation per
    ``(serial, kind)``, bounds fleet-wide recovery concurrency, and opens a
    short per-serial breaker after repeated failures.
    """

    def __init__(
        self,
        *,
        max_concurrency: int,
        breaker_failures: int = 3,
        breaker_base_s: float = 5.0,
        breaker_max_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if breaker_failures < 1:
            raise ValueError("breaker_failures must be at least 1")
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="relay-recovery",
        )
        self._breaker_failures = breaker_failures
        self._breaker_base_s = max(0.0, float(breaker_base_s))
        self._breaker_max_s = max(self._breaker_base_s, float(breaker_max_s))
        self._clock = clock
        self._lock = threading.Lock()
        self._inflight: dict[tuple[str, str], Future[RecoveryResult]] = {}
        self._breakers: dict[str, _BreakerState] = {}
        self._closed = False
        self._active = 0
        self._max_active_seen = 0
        self._counters: defaultdict[str, int] = defaultdict(int)

    def submit(
        self,
        serial: str,
        kind: str,
        operation: Callable[[], RecoveryResult],
        *,
        force: bool = False,
    ) -> Future[RecoveryResult]:
        """Return a shared future for duplicate work, or admit one new job."""
        serial = str(serial or "").strip()
        kind = str(kind or "").strip()
        if not serial or not kind:
            return _completed_future(("recovery serial/kind is required", -1))

        now = self._clock()
        key = (serial, kind)
        with self._lock:
            if self._closed:
                raise RuntimeError("recovery coordinator is shut down")
            current = self._inflight.get(key)
            if current is not None:
                self._counters["coalesced"] += 1
                self._counters[f"coalesced_{kind}"] += 1
                return current

            breaker = self._breakers.get(serial)
            if (
                not force
                and breaker is not None
                and breaker.opened_until > now
            ):
                remaining_ms = round((breaker.opened_until - now) * 1_000)
                self._counters["skipped_breaker"] += 1
                self._counters[f"skipped_breaker_{kind}"] += 1
                return _completed_future((
                    (
                        f"recovery breaker open for {serial} "
                        f"({remaining_ms}ms remaining)"
                    ),
                    -1,
                ))

            self._counters["started"] += 1
            self._counters[f"started_{kind}"] += 1
            future = self._executor.submit(
                self._run_operation,
                serial,
                kind,
                operation,
            )
            self._inflight[key] = future

        future.add_done_callback(
            lambda completed, admitted_key=key: self._remove_completed(
                admitted_key,
                completed,
            )
        )
        return future

    def _run_operation(
        self,
        serial: str,
        kind: str,
        operation: Callable[[], RecoveryResult],
    ) -> RecoveryResult:
        with self._lock:
            self._active += 1
            self._max_active_seen = max(self._max_active_seen, self._active)
        try:
            output, rc = operation()
            self._record_completion(serial, kind, rc)
            return output, rc
        except Exception:
            self._record_completion(serial, kind, -1)
            raise
        finally:
            with self._lock:
                self._active = max(0, self._active - 1)

    def _record_completion(self, serial: str, kind: str, rc: int) -> None:
        now = self._clock()
        with self._lock:
            if rc == 0:
                self._counters["succeeded"] += 1
                self._counters[f"succeeded_{kind}"] += 1
                self._breakers.pop(serial, None)
                return

            self._counters["failed"] += 1
            self._counters[f"failed_{kind}"] += 1
            breaker = self._breakers.setdefault(serial, _BreakerState())
            breaker.failures += 1
            if breaker.failures >= self._breaker_failures:
                over = breaker.failures - self._breaker_failures
                delay = min(
                    self._breaker_max_s,
                    self._breaker_base_s * (2 ** min(over, 10)),
                )
                breaker.opened_until = max(breaker.opened_until, now + delay)
                self._counters["breaker_opened"] += 1
                self._counters[f"breaker_opened_{kind}"] += 1

    def _remove_completed(
        self,
        key: tuple[str, str],
        completed: Future[RecoveryResult],
    ) -> None:
        with self._lock:
            if self._inflight.get(key) is completed:
                self._inflight.pop(key, None)

    def stats_snapshot(self, *, reset: bool = False) -> dict[str, int]:
        now = self._clock()
        with self._lock:
            data: dict[str, int] = {
                "active": self._active,
                "inflight": len(self._inflight),
                "breaker_open": sum(
                    1
                    for state in self._breakers.values()
                    if state.opened_until > now
                ),
                "max_active": self._max_active_seen,
            }
            data.update(dict(self._counters))
            if reset:
                self._counters.clear()
                self._max_active_seen = self._active
            return data

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=True)


def _completed_future(result: RecoveryResult) -> Future[RecoveryResult]:
    future: Future[RecoveryResult] = Future()
    future.set_result(result)
    return future
