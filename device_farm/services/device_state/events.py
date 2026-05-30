"""Domain events for device FSM changes (DF-T-02-002, DF-T-02-005)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

from db.models.enums import DeviceFsmState

log = logging.getLogger(__name__)

EVENT_TYPE = "device.state_changed"
DEVICE_DEAD_EVENT = "device.dead"
DEVICE_REVIVED_EVENT = "device.revived"
SESSION_LOST_DEVICE_EVENT = "session.lost_device"

_listeners: list[Callable[["DeviceStateChangedEvent"], None]] = []


@dataclass(frozen=True, slots=True)
class DeviceStateChangedEvent:
    device_id: str
    from_state: str
    to_state: str
    event: str
    source: str
    event_id: Optional[str] = None
    session_id: Optional[str] = None
    payload: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def add_device_state_listener(
    fn: Callable[[DeviceStateChangedEvent], None],
) -> Callable[[], None]:
    _listeners.append(fn)

    def _unsubscribe() -> None:
        try:
            _listeners.remove(fn)
        except ValueError:
            pass

    return _unsubscribe


def publish_device_state_changed(event: DeviceStateChangedEvent) -> None:
    for fn in list(_listeners):
        try:
            fn(event)
        except Exception as exc:
            log.warning("device.state_changed listener error: %s", exc)
    _schedule_redis_publish(EVENT_TYPE, event.to_dict())


@dataclass(frozen=True, slots=True)
class DeviceDeadEvent:
    device_id: str
    reason: str
    last_known_state: str
    entered_reconnect_at: Optional[str]
    session_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DeviceRevivedEvent:
    device_id: str
    actor: str
    from_state: str = DeviceFsmState.DEAD.value
    to_state: str = DeviceFsmState.CONNECTING.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SessionLostDeviceEvent:
    device_id: str
    session_id: str
    reason: str
    owner_user_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def publish_device_dead(event: DeviceDeadEvent) -> None:
    payload = {"event": DEVICE_DEAD_EVENT, **event.to_dict()}
    _schedule_redis_publish(DEVICE_DEAD_EVENT, payload)


def publish_device_revived(event: DeviceRevivedEvent) -> None:
    payload = {"event": DEVICE_REVIVED_EVENT, **event.to_dict()}
    _schedule_redis_publish(DEVICE_REVIVED_EVENT, payload)
    _schedule_agent_rebootstrap_hint(event.device_id, actor=event.actor)


def publish_session_lost_device(event: SessionLostDeviceEvent) -> None:
    payload = {"event": SESSION_LOST_DEVICE_EVENT, **event.to_dict()}
    _schedule_redis_publish(SESSION_LOST_DEVICE_EVENT, payload)


def _schedule_agent_rebootstrap_hint(device_id: str, *, actor: str) -> None:
    payload = {
        "event": "device.rebootstrap_hint",
        "device_id": device_id,
        "actor": actor,
    }
    _schedule_redis_publish("device.rebootstrap_hint", payload)


def _schedule_redis_publish(channel_suffix: str, payload: dict[str, Any]) -> None:
    try:
        from services import redis_store

        if not redis_store.enabled():
            return
        client = redis_store.client()
        if client is None:
            return

        channel = redis_store.key(f"events:{channel_suffix}")
        body = json.dumps(payload)

        async def _publish() -> None:
            try:
                await client.publish(channel, body)
            except Exception as exc:
                log.debug("device.state_changed redis publish failed: %s", exc)

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_publish())
        except RuntimeError:
            pass
    except Exception as exc:
        log.debug("device.state_changed redis publish skipped: %s", exc)
