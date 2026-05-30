"""Database connectivity monitor with debounced safe-mode transitions (DF-T-01-007)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from sqlalchemy import text

from core.env import db_ping_debounce_count, db_ping_interval_sec

log = logging.getLogger(__name__)

APP_VERSION = "1.0.0"


class DbHealthMonitor:
    def __init__(
        self,
        *,
        debounce_count: int | None = None,
        started_at: float | None = None,
    ) -> None:
        self.debounce_count = max(1, debounce_count or db_ping_debounce_count())
        self.started_at = started_at or time.time()
        self.db_connected = True
        self.safe_mode = False
        self._success_streak = 0
        self._fail_streak = 0
        self._on_enter: list[Callable[[], None]] = []
        self._on_exit: list[Callable[[], None]] = []

    def on_enter_safe_mode(self, fn: Callable[[], None]) -> None:
        self._on_enter.append(fn)

    def on_exit_safe_mode(self, fn: Callable[[], None]) -> None:
        self._on_exit.append(fn)

    def mark_disconnected(self) -> None:
        self.db_connected = False
        self.safe_mode = True
        self._success_streak = 0
        self._fail_streak = self.debounce_count

    def mark_connected(self) -> None:
        self.db_connected = True
        self.safe_mode = False
        self._fail_streak = 0
        self._success_streak = self.debounce_count

    async def ping_once(self) -> bool:
        try:
            from db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            self._record_success()
            return True
        except Exception as exc:
            log.debug("db health ping failed: %s", exc)
            self._record_failure()
            return False

    def _record_success(self) -> None:
        self._fail_streak = 0
        self._success_streak += 1
        if self.safe_mode and self._success_streak >= self.debounce_count:
            self.safe_mode = False
            self.db_connected = True
            log.warning("runtime.safe_mode_exited")
            for fn in self._on_exit:
                try:
                    fn()
                except Exception:
                    log.debug("safe_mode exit hook failed", exc_info=True)

    def _record_failure(self) -> None:
        self._success_streak = 0
        self._fail_streak += 1
        if not self.safe_mode and self._fail_streak >= self.debounce_count:
            self.safe_mode = True
            self.db_connected = False
            log.warning("runtime.safe_mode_entered")
            for fn in self._on_enter:
                try:
                    fn()
                except Exception:
                    log.debug("safe_mode enter hook failed", exc_info=True)

    def status_payload(self) -> dict:
        return {
            "safe_mode": bool(self.safe_mode),
            "db_connected": bool(self.db_connected),
            "version": APP_VERSION,
            "started_at": self.started_at,
        }


async def db_ping_loop(monitor: DbHealthMonitor, *, stop_event: asyncio.Event | None = None) -> None:
    interval = max(1.0, float(db_ping_interval_sec()))
    while True:
        if stop_event and stop_event.is_set():
            return
        await monitor.ping_once()
        await asyncio.sleep(interval)
