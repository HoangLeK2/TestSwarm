"""Extraction retry policy (DF-T-06-014)."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY = 0.5


async def with_extraction_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    engine: str,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay: float = _DEFAULT_BASE_DELAY,
) -> T:
    """Retry transient extraction failures with exponential backoff + jitter."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        started = asyncio.get_event_loop().time()
        try:
            result = await fn()
            elapsed_ms = (asyncio.get_event_loop().time() - started) * 1000
            try:
                from web.metrics import extraction_latency_ms

                extraction_latency_ms.labels(engine=engine).observe(elapsed_ms)
            except Exception:
                pass
            return result
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
            log.warning(
                "extraction retry engine=%s attempt=%s/%s delay=%.2fs err=%s",
                engine,
                attempt,
                max_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
