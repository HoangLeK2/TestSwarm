"""In-process execution event bus for SSE subscribers (DF-T-04-013)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)

_SENTINEL: Any = object()


class ExecutionEventBus:
    """Fan-out published events to live SSE subscribers keyed by execution_id."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, execution_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs[execution_id].append(queue)
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            async with self._lock:
                subs = self._subs.get(execution_id, [])
                if queue in subs:
                    subs.remove(queue)
                if not subs:
                    self._subs.pop(execution_id, None)

    async def publish(self, execution_id: str, envelope: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subs.get(execution_id, []))
        for queue in queues:
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                log.debug("execution event bus backpressure execution=%s", execution_id[:8])
                try:
                    from web.metrics import execution_event_bus_backpressure_total

                    execution_event_bus_backpressure_total.inc()
                except Exception:
                    pass

    async def close_subscriber(self, execution_id: str, queue: asyncio.Queue[Any]) -> None:
        try:
            queue.put_nowait(_SENTINEL)
        except asyncio.QueueFull:
            pass

    @asynccontextmanager
    async def subscription(self, execution_id: str) -> AsyncIterator[asyncio.Queue[Any]]:
        """Register a subscriber queue and always remove it on exit."""
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs[execution_id].append(queue)
        try:
            yield queue
        finally:
            await self.close_subscriber(execution_id, queue)
            async with self._lock:
                subs = self._subs.get(execution_id, [])
                if queue in subs:
                    subs.remove(queue)
                if not subs:
                    self._subs.pop(execution_id, None)
            with contextlib.suppress(asyncio.QueueEmpty):
                while not queue.empty():
                    queue.get_nowait()


_bus: ExecutionEventBus | None = None


def get_execution_event_bus() -> ExecutionEventBus:
    global _bus
    if _bus is None:
        _bus = ExecutionEventBus()
    return _bus
