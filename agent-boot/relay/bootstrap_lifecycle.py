"""Concurrency and duplicate control for slow per-device bootstrap work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

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
            base = min(
                self.startup_base_s * (2 ** (attempt - 1)),
                self.startup_max_s,
            )
        else:
            base = min(
                self.steady_base_s * (2 ** attempt),
                self.steady_max_s,
            )
        return base * (1.0 + 0.2 * jitter_ratio)


@dataclass(slots=True)
class _BootstrapRun:
    done: threading.Event = field(default_factory=threading.Event)
    result: BootstrapResult | None = None
    error: BaseException | None = None


class BootstrapCoordinator:
    """Run at most one bootstrap per phone and bound fleet-wide repair pressure."""

    def __init__(self, *, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._lock = threading.Lock()
        self._inflight: dict[str, _BootstrapRun] = {}

    def run(
        self,
        serial: str,
        operation: Callable[[], BootstrapResult],
        *,
        wait_timeout: float,
    ) -> BootstrapResult:
        serial = str(serial or "").strip()
        if not serial:
            return "bootstrap serial is required", -1

        with self._lock:
            current = self._inflight.get(serial)
            if current is None:
                current = _BootstrapRun()
                self._inflight[serial] = current
                owner = True
            else:
                owner = False

        if not owner:
            if not current.done.wait(timeout=max(0.0, wait_timeout)):
                return f"bootstrap still running for {serial}", -1
            if current.error is not None:
                raise RuntimeError(
                    f"bootstrap failed for {serial}: {current.error}"
                ) from current.error
            return current.result or (f"bootstrap returned no result for {serial}", -1)

        try:
            with self._slots:
                current.result = operation()
                return current.result
        except BaseException as exc:
            current.error = exc
            raise
        finally:
            current.done.set()
            with self._lock:
                if self._inflight.get(serial) is current:
                    self._inflight.pop(serial, None)
