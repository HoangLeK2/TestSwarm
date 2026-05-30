"""Background worker — auto-release idle reserve sessions (DF-T-02-004)."""
from __future__ import annotations

import asyncio
import logging
import os

from db.database import AsyncSessionLocal
from services.device_reserve.service import auto_release_expired_sessions

log = logging.getLogger(__name__)

AUTO_RELEASE_INTERVAL_SEC = int(os.environ.get("DEVICE_AUTO_RELEASE_INTERVAL_SEC", "30"))
AUTO_RELEASE_BATCH_LIMIT = int(os.environ.get("DEVICE_AUTO_RELEASE_BATCH_LIMIT", "200"))


async def auto_release_once() -> int:
    async with AsyncSessionLocal() as db:
        try:
            count = await auto_release_expired_sessions(
                db, limit=AUTO_RELEASE_BATCH_LIMIT
            )
            await db.commit()
            return count
        except Exception:
            await db.rollback()
            raise


async def auto_release_loop() -> None:
    log.info(
        "device auto-release worker started (interval=%ss batch=%s)",
        AUTO_RELEASE_INTERVAL_SEC,
        AUTO_RELEASE_BATCH_LIMIT,
    )
    while True:
        try:
            released = await auto_release_once()
            if released:
                log.info("device auto-release released %s session(s)", released)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("device auto-release worker iteration failed")
        await asyncio.sleep(AUTO_RELEASE_INTERVAL_SEC)
