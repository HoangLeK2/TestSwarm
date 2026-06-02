"""Background worker — auto-release idle reserve sessions (DF-T-02-004)."""
from __future__ import annotations

import asyncio
import logging
import os

from db.database import AsyncSessionLocal

log = logging.getLogger(__name__)

AUTO_RELEASE_INTERVAL_SEC = int(os.environ.get("DEVICE_AUTO_RELEASE_INTERVAL_SEC", "30"))
AUTO_RELEASE_BATCH_LIMIT = int(os.environ.get("DEVICE_AUTO_RELEASE_BATCH_LIMIT", "200"))


async def auto_release_once() -> int:
    from db.database import schema_init_ok
    from db.crud import device_reserve_session as reserve_repo
    from services.device_reserve.service import try_auto_release_session

    if schema_init_ok is not True:
        return 0

    async with AsyncSessionLocal() as db:
        candidates = await reserve_repo.list_expired_active_sessions(
            db, limit=AUTO_RELEASE_BATCH_LIMIT
        )

    released = 0
    for row in candidates:
        async with AsyncSessionLocal() as db:
            try:
                if await try_auto_release_session(db, row.id):
                    await db.commit()
                    released += 1
            except Exception:
                await db.rollback()
    return released


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
