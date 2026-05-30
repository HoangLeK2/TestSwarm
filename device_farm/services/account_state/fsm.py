"""Account lifecycle FSM — five states with explicit transition rules (DF-T-07-005)."""
from __future__ import annotations

from typing import Final

from db.models.enums import AccountState

# Allowed targets from each source state (auto cooldown→active is handled by cron, not API).
_TRANSITIONS: Final[dict[AccountState, frozenset[AccountState]]] = {
    AccountState.ACTIVE: frozenset(
        {
            AccountState.COOLDOWN,
            AccountState.SUSPENDED,
            AccountState.BANNED,
            AccountState.RETIRED,
        }
    ),
    AccountState.COOLDOWN: frozenset(
        {
            AccountState.ACTIVE,
            AccountState.SUSPENDED,
            AccountState.RETIRED,
        }
    ),
    AccountState.SUSPENDED: frozenset(
        {
            AccountState.ACTIVE,
            AccountState.BANNED,
            AccountState.RETIRED,
        }
    ),
    AccountState.BANNED: frozenset({AccountState.RETIRED}),
    AccountState.RETIRED: frozenset(),
}

_TERMINAL = frozenset({AccountState.RETIRED})


def normalize_state(value: str | AccountState | None) -> AccountState:
    """Map legacy ``status`` values onto FSM states."""
    if value is None:
        return AccountState.ACTIVE
    if isinstance(value, AccountState):
        return value
    raw = str(value).strip().lower()
    if raw == "disabled":
        return AccountState.SUSPENDED
    try:
        return AccountState(raw)
    except ValueError:
        raise ValueError(f"unknown account state: {value!r}") from None


def can_transition(from_state: str | AccountState, to_state: str | AccountState) -> bool:
    src = normalize_state(from_state)
    dst = normalize_state(to_state)
    if src == dst:
        return False
    return dst in _TRANSITIONS.get(src, frozenset())


def transition_error_message(from_state: str | AccountState, to_state: str | AccountState) -> str:
    src = normalize_state(from_state)
    dst = normalize_state(to_state)
    if src in _TERMINAL:
        return f"{src.value} là terminal state"
    allowed = sorted(s.value for s in _TRANSITIONS.get(src, frozenset()))
    return (
        f"cannot transition from {src.value} to {dst.value}; "
        f"allowed: {', '.join(allowed) or '(none)'}"
    )


def all_transition_pairs() -> list[tuple[AccountState, AccountState, bool]]:
    """Enumerate every (from, to) pair and whether it is allowed — for matrix tests."""
    pairs: list[tuple[AccountState, AccountState, bool]] = []
    for src in AccountState:
        for dst in AccountState:
            if src == dst:
                continue
            pairs.append((src, dst, can_transition(src, dst)))
    return pairs
