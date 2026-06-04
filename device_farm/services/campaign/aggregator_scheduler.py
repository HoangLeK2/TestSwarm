"""Debounced campaign status aggregation (DF-T-04-007 / DF-T-04-010)."""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

log = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 0.5
_pending: dict[str, asyncio.Task[Any]] = {}
_lock = asyncio.Lock()


def _sync_mode() -> bool:
    """Run aggregation inline under pytest; debounce in production."""
    return "pytest" in sys.modules


async def request_campaign_status_evaluation(
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None = None,
    reason: str | None = None,
    sync: bool | None = None,
) -> None:
    """Schedule (or run immediately) campaign terminal status recompute."""
    if sync if sync is not None else _sync_mode():
        await _evaluate_now(
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user_id,
            reason=reason,
        )
        return

    async with _lock:
        existing = _pending.get(campaign_id)
        if existing and not existing.done():
            existing.cancel()
        task = asyncio.create_task(
            _debounced_evaluate(
                campaign_id=campaign_id,
                org_id=org_id,
                user_id=user_id,
                reason=reason,
            ),
            name=f"campaign-agg-{campaign_id[:8]}",
        )
        _pending[campaign_id] = task


async def _debounced_evaluate(
    *,
    campaign_id: str,
    org_id: str,
    user_id: str | None,
    reason: str | None,
) -> None:
    try:
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        await _evaluate_now(
            org_id=org_id,
            campaign_id=campaign_id,
            user_id=user_id,
            reason=reason,
        )
    except asyncio.CancelledError:
        return
    except Exception:
        log.warning(
            "campaign aggregator failed campaign=%s org=%s",
            campaign_id,
            org_id,
            exc_info=True,
        )
    finally:
        async with _lock:
            if _pending.get(campaign_id) is asyncio.current_task():
                _pending.pop(campaign_id, None)


async def _evaluate_now(
    *,
    org_id: str,
    campaign_id: str,
    user_id: str | None,
    reason: str | None,
) -> None:
    from db.database import activity_session
    from services.campaign.aggregator import evaluate_campaign_status
    from tenancy.context import tenant_context

    async with activity_session() as db:
        with tenant_context(org_id):
            await evaluate_campaign_status(
                db,
                org_id=org_id,
                campaign_id=campaign_id,
                user_id=user_id,
                reason=reason,
            )


async def flush_pending_evaluations() -> None:
    """Await all debounced aggregations — for tests/shutdown hooks."""
    async with _lock:
        tasks = [t for t in _pending.values() if not t.done()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
