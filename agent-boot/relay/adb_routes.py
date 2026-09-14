"""relay/adb_routes.py — serial → ADB endpoint routing table.

agent-boot can be pointed at several independent ADB servers (``:5037``,
``:5038``, ``:5039``, …) via ``ADB_SERVER_SOCKETS``. A device lives on exactly
one of them, so every ADB command needs to know which. This module owns that
mapping so the hot path is a dict lookup instead of a scan of every endpoint:

    serial → route.endpoint → adb -H <host> -P <port> -s <serial> …

Writers:
  * the per-endpoint ``track-devices`` watchers, via :meth:`sync_endpoint`
  * a single-flight discovery scan on a cache miss, via :meth:`resolve`

Duplicate-serial policy: the endpoint that most recently reported the serial as
``state=device`` wins. Snapshots that do not contain the serial only remove a
route that still points at *that* endpoint, so two trackers racing over the same
serial converge on the newest ``device`` report instead of flapping.

Thread-safe — agent-boot runs blocking ADB calls from a thread pool.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

logger = logging.getLogger("relay.adb.routes")


@dataclass(frozen=True, slots=True)
class AdbEndpoint:
    """One ADB server (``adb -H host -P port``)."""

    host: str
    port: int

    @property
    def flags(self) -> list[str]:
        return ["-H", self.host, "-P", str(self.port)]

    def __str__(self) -> str:  # log-friendly
        return f"{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class DeviceRoute:
    serial: str
    endpoint: AdbEndpoint
    state: str
    last_seen: float


DiscoverFn = Callable[[str], AdbEndpoint | None]


class AdbRouteTable:
    """Concurrency-safe ``serial → AdbEndpoint`` map with single-flight discovery."""

    #: Two endpoint changes closer together than this mean both servers are
    #: claiming the device, not that it moved twice.
    CONFLICT_WINDOW_S = 10.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._routes: dict[str, DeviceRoute] = {}
        self._discovery_locks: dict[str, threading.Lock] = {}
        self._stats: dict[str, int] = {}
        self._last_endpoint_change: dict[str, float] = {}

    # ── reads ────────────────────────────────────────────────────────────────

    def get(self, serial: str) -> DeviceRoute | None:
        serial = str(serial or "").strip()
        if not serial:
            return None
        with self._lock:
            route = self._routes.get(serial)
            self._bump("hit" if route else "miss")
            return route

    def snapshot(self) -> dict[str, DeviceRoute]:
        with self._lock:
            return dict(self._routes)

    def stats(self, *, reset: bool = False) -> dict[str, int]:
        with self._lock:
            stats = dict(self._stats)
            if reset:
                self._stats.clear()
            return stats

    # ── writes ───────────────────────────────────────────────────────────────

    def set(
        self,
        serial: str,
        endpoint: AdbEndpoint,
        *,
        state: str = "device",
    ) -> DeviceRoute | None:
        serial = str(serial or "").strip()
        if not serial:
            return None
        with self._lock:
            previous = self._routes.get(serial)
            route = DeviceRoute(
                serial=serial,
                endpoint=endpoint,
                state=state,
                last_seen=time.monotonic(),
            )
            self._routes[serial] = route
            if previous is None:
                self._bump("discovered")
                logger.info(
                    "device route discovered serial=%s adb_host=%s adb_port=%d state=%s",
                    serial,
                    endpoint.host,
                    endpoint.port,
                    state,
                )
            elif previous.endpoint != endpoint:
                self._bump("changed")
                logger.info(
                    "device route changed serial=%s old_port=%d new_port=%d "
                    "old_host=%s new_host=%s",
                    serial,
                    previous.endpoint.port,
                    endpoint.port,
                    previous.endpoint.host,
                    endpoint.host,
                )
                self._note_endpoint_change(serial, previous.endpoint, endpoint)
            return route

    def update_state(self, serial: str, state: str) -> None:
        with self._lock:
            route = self._routes.get(str(serial or "").strip())
            if route is None or route.state == state:
                return
            self._routes[route.serial] = DeviceRoute(
                serial=route.serial,
                endpoint=route.endpoint,
                state=state,
                last_seen=time.monotonic(),
            )

    def remove(
        self,
        serial: str,
        *,
        reason: str,
        only_endpoint: AdbEndpoint | None = None,
    ) -> DeviceRoute | None:
        """Drop the route for ``serial``.

        ``only_endpoint`` makes the removal conditional: a tracker reporting
        that a serial vanished from *its* endpoint must not delete a route that
        another tracker has since pointed elsewhere.
        """
        serial = str(serial or "").strip()
        if not serial:
            return None
        with self._lock:
            route = self._routes.get(serial)
            if route is None:
                return None
            if only_endpoint is not None and route.endpoint != only_endpoint:
                return None
            del self._routes[serial]
            self._bump("invalidated")
        logger.info(
            "device route invalidated serial=%s old_host=%s old_port=%d reason=%s",
            serial,
            route.endpoint.host,
            route.endpoint.port,
            reason,
        )
        return route

    def sync_endpoint(
        self,
        endpoint: AdbEndpoint,
        snapshot: Mapping[str, str],
    ) -> None:
        """Apply one endpoint's full device snapshot (from ``track-devices``).

        Serials reported as ``device`` claim the endpoint; serials that are gone
        from the snapshot lose their route to it. This is what makes a device
        moving between ADB servers self-heal without a restart.
        """
        for serial, state in snapshot.items():
            if state == "device":
                self.set(serial, endpoint, state=state)
        present = set(snapshot)
        with self._lock:
            vanished = [
                serial
                for serial, route in self._routes.items()
                if route.endpoint == endpoint and serial not in present
            ]
        for serial in vanished:
            self.remove(serial, reason="gone_from_endpoint", only_endpoint=endpoint)

    # ── discovery ────────────────────────────────────────────────────────────

    def resolve(self, serial: str, discover: DiscoverFn) -> DeviceRoute | None:
        """Cache-first lookup; on a miss run ``discover`` once per serial.

        Concurrent callers for the same uncached serial share one scan.
        """
        route = self.get(serial)
        if route is not None:
            return route
        return self._discover_once(serial, discover, expected=None)

    def invalidate_and_resolve(
        self,
        serial: str,
        discover: DiscoverFn,
        *,
        reason: str,
    ) -> DeviceRoute | None:
        """Drop a route that just failed, then rediscover it (single-flight)."""
        stale = self.get(serial)
        if stale is None:
            return self._discover_once(serial, discover, expected=None)
        self.remove(serial, reason=reason, only_endpoint=stale.endpoint)
        return self._discover_once(serial, discover, expected=stale)

    def _discover_once(
        self,
        serial: str,
        discover: DiscoverFn,
        *,
        expected: DeviceRoute | None,
    ) -> DeviceRoute | None:
        serial = str(serial or "").strip()
        if not serial:
            return None
        with self._lock:
            lock = self._discovery_locks.setdefault(serial, threading.Lock())
        with lock:
            # Another thread may have resolved this serial while we queued. Its
            # result counts unless it is the very route we came here to replace.
            current = self.get(serial)
            if current is not None and current.endpoint != getattr(expected, "endpoint", None):
                return current
            with self._lock:
                self._bump("discovery_scans")
            endpoint = discover(serial)
            if endpoint is None:
                return None
            return self.set(serial, endpoint)

    # ── internals ────────────────────────────────────────────────────────────

    def _note_endpoint_change(
        self,
        serial: str,
        old: AdbEndpoint,
        new: AdbEndpoint,
    ) -> None:
        """Flag a serial that two ADB servers are both claiming.

        A device that genuinely moves changes endpoint once: the old server loses
        it, the new one gains it, and it stays. Two servers sharing one USB
        device instead flip the route back and forth as their trackers take
        turns reporting, and every command follows whichever reported last. That
        is a real ownership conflict and an operator has to resolve it — the
        route table cannot tell which server should own the device.

        Caller holds ``self._lock``.
        """
        now = time.monotonic()
        previous_change = self._last_endpoint_change.get(serial)
        self._last_endpoint_change[serial] = now
        if previous_change is None or now - previous_change >= self.CONFLICT_WINDOW_S:
            return
        self._bump("conflicts")
        logger.warning(
            "device route conflict serial=%s endpoints=%s,%s since_last_change_s=%.2f "
            "— both ADB servers claim this device; commands follow the newest report",
            serial,
            old,
            new,
            now - previous_change,
        )

    def _bump(self, key: str) -> None:
        self._stats[key] = self._stats.get(key, 0) + 1

    def clear(self) -> None:
        with self._lock:
            self._routes.clear()
            self._discovery_locks.clear()
            self._stats.clear()
            self._last_endpoint_change.clear()


#: Process-wide table. agent-boot talks to one set of ADB servers per process.
route_table = AdbRouteTable()
