"""Subscribe to agent.state_event and apply device FSM (DF-T-02-002)."""
from __future__ import annotations

import logging

from db.database import AsyncSessionLocal
from services.device_state.bus import AGENT_STATE_EVENT_TOPIC, AgentStateEvent, subscribe
from services.device_state.service import DeviceStateService

log = logging.getLogger(__name__)

_service = DeviceStateService()
_unsubscribe = None


async def _handle_agent_state_event(event: AgentStateEvent) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await _service.apply_event(
                db,
                event.device_id,
                event=event.event,
                source=event.source,
                event_id=event.event_id,
                payload=event.payload,
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log.warning(
                "agent state event apply failed device=%s event=%s: %s",
                event.device_id,
                event.event,
                exc,
            )


def start_agent_state_consumer() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        return
    _unsubscribe = subscribe(AGENT_STATE_EVENT_TOPIC, _handle_agent_state_event)
    log.info("device FSM agent.state_event consumer started")


def stop_agent_state_consumer() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None
