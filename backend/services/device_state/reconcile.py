"""Hourly reconcile placeholder — compare agent report vs control-plane store (DF-T-02-002)."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def device_fsm_reconcile_loop(*, interval_seconds: int = 3600) -> None:
    """Placeholder reconcile job — logs sample drift check hook for DF-T-02-005."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await _reconcile_sample()
        except Exception as exc:
            log.warning("device_fsm_reconcile failed: %s", exc)


async def _reconcile_sample() -> None:
    """Compare a sample of devices; full implementation deferred to drift ticket."""
    log.debug(
        "device_fsm_reconcile placeholder — hourly sample compare agent vs store (not yet implemented)"
    )
