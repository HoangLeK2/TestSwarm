"""In-process pub/sub for agent → control-plane state events (DF-T-02-002)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

AGENT_STATE_EVENT_TOPIC = "agent.state_event"

_subscribers: dict[str, list[Callable[[Any], Any]]] = {}


@dataclass(frozen=True, slots=True)
class AgentStateEvent:
    device_id: str
    event: str
    event_id: str
    source: str = "agent"
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def subscribe(topic: str, handler: Callable[[Any], Any]) -> Callable[[], None]:
    _subscribers.setdefault(topic, []).append(handler)

    def _unsubscribe() -> None:
        try:
            _subscribers[topic].remove(handler)
        except (KeyError, ValueError):
            pass

    return _unsubscribe


async def publish(topic: str, message: Any) -> None:
    for handler in list(_subscribers.get(topic, [])):
        try:
            result = handler(message)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            log.warning("bus handler error topic=%s: %s", topic, exc)


async def publish_agent_state_event(event: AgentStateEvent) -> None:
    await publish(AGENT_STATE_EVENT_TOPIC, event)
