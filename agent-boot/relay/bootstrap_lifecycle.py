"""Concurrency and duplicate control for slow per-device bootstrap work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

BootstrapResult = tuple[str, int]


@dataclass(frozen=True, slots=True)
class RelayRetryPolicy:
    """Retry quickly during process startup, then use conservative backoff."""

    startup_window_s: float = 30.0
    startup_base_s: float = 0.25
    startup_max_s: float = 2.0
    steady_base_s: float = 0.5
    steady_max_s: float = 8.0

    def delay(
        self,
        *,
        attempt: int,
        startup_elapsed: float,
        jitter_ratio: float,
    ) -> float:
        attempt = max(1, int(attempt))
        jitter_ratio = min(max(float(jitter_ratio), 0.0), 1.0)
        if startup_elapsed < self.startup_window_s:
            exponent = min(attempt - 1, 62)
            base = min(
                self.startup_base_s * (2 ** exponent),
                self.startup_max_s,
            )
        else:
            exponent = min(attempt, 62)
            base = min(
                self.steady_base_s * (2 ** exponent),
                self.steady_max_s,
            )
        return base * (1.0 + 0.2 * jitter_ratio)


class BootstrapCoordinator:
    """Coalesce per-phone work on a dedicated bounded bootstrap executor."""

    def __init__(self, *, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="relay-bootstrap",
        )
        self._lock = threading.Lock()
        self._inflight: dict[str, Future[BootstrapResult]] = {}
        self._closed = False

    def submit(
        self,
        serial: str,
        operation: Callable[[], BootstrapResult],
    ) -> Future[BootstrapResult]:
        """Return the existing per-phone future or admit one new repair."""
        serial = str(serial or "").strip()
        if not serial:
            future: Future[BootstrapResult] = Future()
            future.set_result(("bootstrap serial is required", -1))
            return future

        with self._lock:
            if self._closed:
                raise RuntimeError("bootstrap coordinator is shut down")
            current = self._inflight.get(serial)
            if current is not None:
                return current
            current = self._executor.submit(operation)
            self._inflight[serial] = current

        current.add_done_callback(
            lambda completed, key=serial: self._remove_completed(key, completed)
        )
        return current

    def _remove_completed(
        self,
        serial: str,
        completed: Future[BootstrapResult],
    ) -> None:
        with self._lock:
            if self._inflight.get(serial) is completed:
                self._inflight.pop(serial, None)

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=True)
