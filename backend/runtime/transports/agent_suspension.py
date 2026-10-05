"""Which agents are administratively switched off, in memory, for the transports.

Refusing a disabled agent's connection looked right and behaved badly: the agent
retried forever, every retry wrote two log lines on the server and one on the
agent, re-enabling had to wait for the next retry, and a reconnect that arrived
before its phone list did slipped through the register-time check entirely.

So the transports keep the connection and park it instead. A parked connection
is held outside every lookup map — `conn_for_serial`, `online_relay_ids`, the
serial index — so nothing can route to it, exactly as if it had been cut. The
difference is that resuming is a dictionary move rather than a reconnect.

This registry is the single answer to "is this parked?", shared by the three
transports so they cannot disagree. It is memory-only and rebuilt from the
database at startup; the database row stays the source of truth.
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable, Optional

log = logging.getLogger(__name__)


class AgentSuspensionRegistry:
    """Relay ids and serials that must not be routed until an admin re-enables."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._relay_ids: set[str] = set()
        self._serials: set[str] = set()

    @staticmethod
    def _clean(values: Iterable[str] | None) -> set[str]:
        out: set[str] = set()
        for value in values or ():
            text = str(value or "").strip()
            if text and not text.startswith("pending-"):
                out.add(text)
        return out

    def suspend(self, relay_id: str, serials: Iterable[str] | None = None) -> None:
        relay = str(relay_id or "").strip()
        with self._lock:
            if relay:
                self._relay_ids.add(relay)
            self._serials |= self._clean(serials)

    def resume(self, relay_id: str, serials: Iterable[str] | None = None) -> None:
        relay = str(relay_id or "").strip()
        with self._lock:
            self._relay_ids.discard(relay)
            self._serials -= self._clean(serials)

    def replace(self, entries: Iterable[tuple[str, Iterable[str] | None]]) -> None:
        """Rebuild from the database — used once at startup."""
        relay_ids: set[str] = set()
        serials: set[str] = set()
        for relay_id, agent_serials in entries:
            relay = str(relay_id or "").strip()
            if relay:
                relay_ids.add(relay)
            serials |= self._clean(agent_serials)
        with self._lock:
            self._relay_ids = relay_ids
            self._serials = serials
        if relay_ids:
            log.info(
                "agent suspension registry loaded: %d agent(s), %d serial(s)",
                len(relay_ids),
                len(serials),
            )

    def is_relay_suspended(self, relay_id: Optional[str]) -> bool:
        relay = str(relay_id or "").strip()
        if not relay:
            return False
        with self._lock:
            return relay in self._relay_ids

    def is_serial_suspended(self, serial: Optional[str]) -> bool:
        text = str(serial or "").strip()
        if not text:
            return False
        with self._lock:
            return text in self._serials

    def any_serial_suspended(self, serials: Iterable[str] | None) -> bool:
        wanted = self._clean(serials)
        if not wanted:
            return False
        with self._lock:
            return bool(wanted & self._serials)

    def snapshot(self) -> tuple[set[str], set[str]]:
        with self._lock:
            return set(self._relay_ids), set(self._serials)


_registry = AgentSuspensionRegistry()


def get_agent_suspension_registry() -> AgentSuspensionRegistry:
    return _registry
