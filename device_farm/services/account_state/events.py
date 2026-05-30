"""Domain events for account state changes (DF-T-07-005)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional

from db.models.enums import AccountEventType
from services.account_event_recorder import get_account_event_recorder

log = logging.getLogger(__name__)

EVENT_TYPE = "account.state.changed"


@dataclass(frozen=True, slots=True)
class AccountStateChangedEvent:
    account_id: str
    from_state: str
    to_state: str
    reason: str
    ttl_seconds: Optional[int]
    actor: str
    platform: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def publish_account_state_changed(event: AccountStateChangedEvent) -> None:
    """Record audit timeline entry and best-effort Redis fan-out."""
    payload = event.to_dict()
    get_account_event_recorder().record(
        account_id=event.account_id,
        event_type=AccountEventType.STATE_CHANGED,
        user_id=event.actor if event.actor != "system" else None,
        platform=event.platform,
        details={
            "event": EVENT_TYPE,
            "from": event.from_state,
            "to": event.to_state,
            "reason": event.reason,
            "ttl_seconds": event.ttl_seconds,
            "actor": event.actor,
        },
    )
    _schedule_redis_publish(payload)


def _schedule_redis_publish(payload: dict[str, Any]) -> None:
    try:
        from services import redis_store

        if not redis_store.enabled():
            return
        client = redis_store.client()
        if client is None:
            return

        channel = redis_store.key("events:account.state.changed")
        body = json.dumps(payload)

        async def _publish() -> None:
            try:
                await client.publish(channel, body)
            except Exception as exc:
                log.debug("account.state.changed redis publish failed: %s", exc)

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_publish())
        except RuntimeError:
            pass
    except Exception as exc:
        log.debug("account.state.changed redis publish skipped: %s", exc)
