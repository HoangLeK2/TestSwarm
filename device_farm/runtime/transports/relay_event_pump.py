"""relay_event_pump.py — batched, deduped relay → device-FSM event pump.

Why this exists
---------------
Relay device online/offline callbacks fire synchronously on the event loop that
also serves the HTTP API. Each one used to schedule its own
``apply_relay_online`` coroutine, and each of those opened its own DB session.
An agent-boot reporting 100 phones therefore asked for 100 concurrent
connections against a pool of ``pool_size=12, max_overflow=3`` — the pool went
dry, every API request blocked on ``pool_timeout=5``, and the backend looked
hung until registration finished.

This pump replaces the fan-out with one worker:

  * callbacks call :meth:`RelayEventPump.submit` — non-blocking, never awaits
  * events are coalesced over a short window and deduped by serial
  * one DB session serves the whole batch, committed once

so the relay FSM path costs exactly one pooled connection no matter how many
phones a relay reports.

The queue is bounded on purpose. If the worker cannot keep up, ``submit``
returns ``False`` and increments ``dropped`` rather than letting an unbounded
backlog grow — visible backpressure beats a slow memory leak. ``stats()`` is
surfaced by ``GET /api/relay/status``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from runtime.stream_telemetry import _Latency

log = logging.getLogger(__name__)

# Sentinel pushed by stop() so the worker wakes immediately instead of waiting
# out the coalesce window.
_STOP = object()


@dataclass(frozen=True)
class RelayFsmEvent:
    """One relay transport transition awaiting its FSM write."""

    kind: str  # "online" | "offline"
    serial: str
    logical_serial: Optional[str] = None
    hardware_serial: Optional[str] = None


ApplyFn = Callable[..., Awaitable[bool]]


class RelayEventPump:
    """Single-worker, batching pump for relay FSM writes."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any],
        apply_online: ApplyFn,
        apply_offline: ApplyFn,
        queue_max: int = 4096,
        batch_max: int = 64,
        coalesce_ms: int = 20,
        name: str = "relay-fsm",
    ) -> None:
        self._session_factory = session_factory
        self._apply_online = apply_online
        self._apply_offline = apply_offline
        self._batch_max = max(1, int(batch_max))
        self._coalesce_s = max(0.0, float(coalesce_ms) / 1000.0)
        self._name = name

        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max(1, int(queue_max)))
        self._worker: Optional[asyncio.Task] = None
        self._stopping = False

        self._submitted = 0
        self._processed = 0
        self._batches = 0
        self._dropped = 0
        self._dropped_published = 0
        self._retries = 0
        self._failed = 0
        self._high_water = 0
        self._last_batch_ms = 0.0
        self._batch_ms = _Latency()
        self._last_error: str = ""
        self._last_error_at: float = 0.0
        self._last_drop_log_at: float = 0.0

    # ── Producer side (event loop, must never block) ────────────────────────

    def submit(
        self,
        kind: str,
        serial: str,
        *,
        logical_serial: Optional[str] = None,
        hardware_serial: Optional[str] = None,
    ) -> bool:
        """Queue one FSM transition. Returns False when dropped.

        Safe to call from any relay callback: it only touches in-memory state
        and returns immediately.
        """
        serial = str(serial or "").strip()
        if not serial or kind not in ("online", "offline"):
            return False
        if self._stopping:
            return False

        event = RelayFsmEvent(
            kind=kind,
            serial=serial,
            logical_serial=logical_serial,
            hardware_serial=hardware_serial,
        )
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1
            self._log_drop(serial)
            return False

        self._submitted += 1
        self._high_water = max(self._high_water, self._queue.qsize())
        return True

    def _log_drop(self, serial: str) -> None:
        """Warn about drops at most once a second — a full queue drops fast."""
        now = time.monotonic()
        if (now - self._last_drop_log_at) < 1.0:
            return
        self._last_drop_log_at = now
        log.warning(
            "%s pump queue full (dropped=%d, depth=%d) — dropping FSM event for %s",
            self._name, self._dropped, self._queue.qsize(), serial,
        )

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stopping = False
        self._worker = asyncio.create_task(self._run(), name=f"{self._name}-pump")
        log.info(
            "%s pump started (batch_max=%d coalesce=%.0fms queue_max=%d)",
            self._name, self._batch_max, self._coalesce_s * 1000, self._queue.maxsize,
        )

    async def stop(self, *, drain_timeout: float = 5.0) -> None:
        """Stop accepting events, drain what is queued, then cancel the worker."""
        worker = self._worker
        if worker is None:
            return
        self._stopping = True
        self._worker = None
        try:
            self._queue.put_nowait(_STOP)
        except asyncio.QueueFull:
            pass
        try:
            await asyncio.wait_for(worker, timeout=max(0.0, drain_timeout))
        except asyncio.TimeoutError:
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("%s pump stop error: %s", self._name, exc)
        log.info(
            "%s pump stopped (processed=%d batches=%d dropped=%d)",
            self._name, self._processed, self._batches, self._dropped,
        )

    # ── Worker ──────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            if first is _STOP:
                # Drain whatever is already queued before leaving.
                batch = self._drain(self._batch_max)
                if batch:
                    await self._run_batch(batch)
                return

            # Coalesce: a relay reporting N phones enqueues N events within a
            # few milliseconds; waiting one window turns N transactions into 1.
            if self._coalesce_s > 0:
                await asyncio.sleep(self._coalesce_s)

            batch = [first]
            stop_seen = False
            for event in self._drain(self._batch_max - 1, allow_stop=True):
                if event is _STOP:
                    stop_seen = True
                    break
                batch.append(event)

            await self._run_batch(batch)
            if stop_seen:
                return

    def _drain(self, limit: int, *, allow_stop: bool = False) -> list:
        """Pull up to ``limit`` queued items without awaiting."""
        items: list = []
        for _ in range(max(0, limit)):
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is _STOP:
                if allow_stop:
                    items.append(_STOP)
                break
            items.append(item)
        return items

    @staticmethod
    def _dedupe(batch: list[RelayFsmEvent]) -> list[RelayFsmEvent]:
        """Collapse to the last event per serial, preserving arrival order.

        A phone that flapped online→offline inside one window only needs its
        final state written, and writing the intermediate one would leave the
        FSM briefly wrong for no benefit.
        """
        latest: dict[str, RelayFsmEvent] = {}
        for event in batch:
            latest[event.serial] = event
        return list(latest.values())

    async def _run_batch(self, batch: list[RelayFsmEvent]) -> None:
        events = self._dedupe(batch)
        if not events:
            return
        started = time.perf_counter()
        try:
            async with self._session_factory() as session:
                for event in events:
                    await self._apply(event, session)
                await session.commit()
            self._processed += len(events)
        except Exception as exc:
            # One bad serial aborts the whole transaction (Postgres), so the
            # rest of the batch has to be replayed on its own session rather
            # than silently lost.
            self._record_error(exc)
            log.warning(
                "%s pump batch of %d failed (%s) — retrying individually",
                self._name, len(events), exc,
            )
            await self._retry_individually(events)
        finally:
            self._batches += 1
            self._last_batch_ms = (time.perf_counter() - started) * 1000.0
            self._batch_ms.record(self._last_batch_ms)
            self._publish_metrics(events)

    async def _retry_individually(self, events: list[RelayFsmEvent]) -> None:
        for event in events:
            self._retries += 1
            try:
                async with self._session_factory() as session:
                    await self._apply(event, session)
                    await session.commit()
                self._processed += 1
            except Exception as exc:
                self._failed += 1
                self._record_error(exc)
                log.warning(
                    "%s pump event failed kind=%s serial=%s: %s",
                    self._name, event.kind, event.serial, exc,
                )

    async def _apply(self, event: RelayFsmEvent, session: Any) -> None:
        fn = self._apply_online if event.kind == "online" else self._apply_offline
        await fn(
            event.serial,
            logical_serial=event.logical_serial,
            hardware_serial=event.hardware_serial,
            db=session,
        )

    def _record_error(self, exc: Exception) -> None:
        self._last_error = f"{type(exc).__name__}: {exc}"
        self._last_error_at = time.time()

    def _publish_metrics(self, events: list[RelayFsmEvent]) -> None:
        try:
            from web.metrics import (
                relay_fsm_batch_seconds,
                relay_fsm_dropped_total,
                relay_fsm_events_total,
                relay_fsm_queue_depth,
            )
        except Exception:
            return
        try:
            relay_fsm_queue_depth.set(self._queue.qsize())
            for kind in ("online", "offline"):
                count = sum(1 for event in events if event.kind == kind)
                if count:
                    relay_fsm_events_total.labels(kind=kind).inc(count)
            # Counters only take deltas — carry the last published total forward.
            drop_delta = self._dropped - self._dropped_published
            if drop_delta > 0:
                relay_fsm_dropped_total.inc(drop_delta)
                self._dropped_published = self._dropped
            relay_fsm_batch_seconds.observe(self._last_batch_ms / 1000.0)
        except Exception:
            pass

    # ── Introspection ───────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Snapshot for GET /api/relay/status — first stop when debugging stalls."""
        return {
            "running": self._worker is not None and not self._worker.done(),
            "depth": self._queue.qsize(),
            "queue_max": self._queue.maxsize,
            "high_water": self._high_water,
            "submitted": self._submitted,
            "processed": self._processed,
            "batches": self._batches,
            "dropped": self._dropped,
            "retries": self._retries,
            "failed": self._failed,
            "last_batch_ms": round(self._last_batch_ms, 3),
            "batch_ms_p95": self._batch_ms.percentile(0.95),
            "batch_ms_max": round(self._batch_ms.max_ms, 3),
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
        }
