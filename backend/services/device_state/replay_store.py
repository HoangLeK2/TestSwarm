"""In-memory replay buffer for lifecycle WS reconnect (DF-T-02-015)."""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


def _replay_ttl_sec() -> float:
    return max(30.0, float(os.environ.get("DEVICE_LIFECYCLE_REPLAY_TTL_SEC", "300")))


def _replay_max_per_org() -> int:
    return max(10, int(os.environ.get("DEVICE_LIFECYCLE_REPLAY_MAX", "500")))


@dataclass
class _OrgReplay:
    events: deque[tuple[float, dict[str, Any]]] = field(default_factory=deque)


class LifecycleReplayStore:
    """Per-organization ring buffer with TTL for minimal reconnect replay."""

    def __init__(self) -> None:
        self._orgs: dict[str, _OrgReplay] = {}
        self._lock = Lock()
        self._ttl = _replay_ttl_sec()
        self._max = _replay_max_per_org()

    def append(self, org_id: str, event: dict[str, Any]) -> None:
        if not org_id:
            return
        now = time.monotonic()
        with self._lock:
            bucket = self._orgs.setdefault(org_id, _OrgReplay())
            bucket.events.append((now, event))
            self._trim_locked(bucket, now)

    def recent(self, org_id: str) -> list[dict[str, Any]]:
        if not org_id:
            return []
        now = time.monotonic()
        with self._lock:
            bucket = self._orgs.get(org_id)
            if bucket is None:
                return []
            self._trim_locked(bucket, now)
            return [item[1] for item in bucket.events]

    def _trim_locked(self, bucket: _OrgReplay, now: float) -> None:
        cutoff = now - self._ttl
        while bucket.events and bucket.events[0][0] < cutoff:
            bucket.events.popleft()
        while len(bucket.events) > self._max:
            bucket.events.popleft()


# Module singleton — process-local replay store (no DB migration required).
replay_store = LifecycleReplayStore()
