"""Device lifecycle FSM — six states with event-driven transitions (DF-T-02-002)."""
from __future__ import annotations

from typing import Final, Literal

from db.models.enums import DeviceFsmEvent, DeviceFsmState

TransitionResult = DeviceFsmState | Literal["IGNORE", "NO_OP", "ILLEGAL"]

_E = DeviceFsmEvent

# (current_state, event_name) -> next state, IGNORE, or absent (= ILLEGAL)
_TRANSITIONS: Final[dict[tuple[DeviceFsmState, str], TransitionResult]] = {
    # UNKNOWN
    (DeviceFsmState.UNKNOWN, _E.ATTACHED.value): DeviceFsmState.CONNECTING,
    (DeviceFsmState.UNKNOWN, _E.DEAD.value): DeviceFsmState.DEAD,
    # CONNECTING
    (DeviceFsmState.CONNECTING, _E.ATTACHED.value): "NO_OP",
    (DeviceFsmState.CONNECTING, _E.ONLINE.value): DeviceFsmState.ONLINE,
    (DeviceFsmState.CONNECTING, _E.RECONNECTING.value): DeviceFsmState.RECONNECTING,
    (DeviceFsmState.CONNECTING, _E.DEAD.value): DeviceFsmState.DEAD,
    # ONLINE
    (DeviceFsmState.ONLINE, _E.ONLINE.value): "NO_OP",
    (DeviceFsmState.ONLINE, _E.SESSION_CLAIM.value): DeviceFsmState.BUSY,
    (DeviceFsmState.ONLINE, _E.RECONNECTING.value): DeviceFsmState.RECONNECTING,
    (DeviceFsmState.ONLINE, _E.DEAD.value): DeviceFsmState.DEAD,
    (DeviceFsmState.ONLINE, _E.BUSY.value): "IGNORE",
    # BUSY — only control plane may enter/leave via session events
    (DeviceFsmState.BUSY, _E.BUSY.value): "IGNORE",
    (DeviceFsmState.BUSY, _E.SESSION_RELEASED.value): DeviceFsmState.ONLINE,
    (DeviceFsmState.BUSY, _E.RECONNECTING.value): DeviceFsmState.RECONNECTING,
    (DeviceFsmState.BUSY, _E.DEAD.value): DeviceFsmState.DEAD,
    # RECONNECTING
    (DeviceFsmState.RECONNECTING, _E.ONLINE.value): DeviceFsmState.ONLINE,
    (DeviceFsmState.RECONNECTING, _E.ATTACHED.value): DeviceFsmState.CONNECTING,
    (DeviceFsmState.RECONNECTING, _E.DEAD.value): DeviceFsmState.DEAD,
    # DEAD — re-pair via attached or admin revive
    (DeviceFsmState.DEAD, _E.ATTACHED.value): DeviceFsmState.CONNECTING,
    (DeviceFsmState.DEAD, _E.REVIVED.value): DeviceFsmState.CONNECTING,
    (DeviceFsmState.DEAD, _E.DEAD.value): "NO_OP",
}

_AGENT_EVENT_VALUES = frozenset(
    e.value
    for e in (
        DeviceFsmEvent.ATTACHED,
        DeviceFsmEvent.ONLINE,
        DeviceFsmEvent.BUSY,
        DeviceFsmEvent.RECONNECTING,
        DeviceFsmEvent.DEAD,
        DeviceFsmEvent.RELEASED,
    )
)

_CONTROL_PLANE_EVENT_VALUES = frozenset(
    e.value
    for e in (
        DeviceFsmEvent.SESSION_CLAIM,
        DeviceFsmEvent.SESSION_RELEASED,
        DeviceFsmEvent.REVIVED,
    )
)

_ADMIN_EVENT_VALUES = frozenset({DeviceFsmEvent.REVIVED.value})


def normalize_state(value: str | DeviceFsmState | None) -> DeviceFsmState:
    if value is None:
        return DeviceFsmState.UNKNOWN
    if isinstance(value, DeviceFsmState):
        return value
    raw = str(value).strip().lower()
    try:
        return DeviceFsmState(raw)
    except ValueError:
        raise ValueError(f"unknown device FSM state: {value!r}") from None


def normalize_event(value: str | DeviceFsmEvent) -> str:
    if isinstance(value, DeviceFsmEvent):
        return value.value
    return str(value).strip()


def resolve_transition(
    from_state: str | DeviceFsmState,
    event: str | DeviceFsmEvent,
    *,
    source: str,
) -> TransitionResult:
    """Return next state, IGNORE, NO_OP, or ILLEGAL."""
    src = normalize_state(from_state)
    evt = normalize_event(event)

    if evt in _CONTROL_PLANE_EVENT_VALUES and source == "agent":
        return "ILLEGAL"

    if evt in _ADMIN_EVENT_VALUES and source not in ("admin", "system"):
        return "ILLEGAL"

    key = (src, evt)
    if key not in _TRANSITIONS:
        return "ILLEGAL"
    return _TRANSITIONS[key]


def all_event_state_pairs() -> list[tuple[DeviceFsmState, str, TransitionResult]]:
    """Enumerate (state, event) pairs for matrix tests."""
    events = sorted(_AGENT_EVENT_VALUES | _CONTROL_PLANE_EVENT_VALUES)
    pairs: list[tuple[DeviceFsmState, str, TransitionResult]] = []
    for state in DeviceFsmState:
        for event in events:
            for source in ("agent", "claim"):
                result = resolve_transition(state, event, source=source)
                pairs.append((state, event, result))
    return pairs
