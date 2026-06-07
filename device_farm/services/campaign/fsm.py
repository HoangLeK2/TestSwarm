"""Campaign lifecycle FSM — controlled status transitions (DF-T-04-007)."""
from __future__ import annotations

from typing import Final

from db.models.enums import CampaignStatus

# Legacy statuses map onto the Epic 04 graph for transition checks.
_LEGACY_AS_DRAFT: Final[frozenset[CampaignStatus]] = frozenset(
    {CampaignStatus.DRAFT, CampaignStatus.IDLE}
)
_LEGACY_AS_RUNNING: Final[frozenset[CampaignStatus]] = frozenset(
    {CampaignStatus.RUNNING, CampaignStatus.PAUSED}
)
_BODY_MUTABLE: Final[frozenset[CampaignStatus]] = frozenset(
    {CampaignStatus.DRAFT, CampaignStatus.IDLE, CampaignStatus.CANCELLED}
)

_TRANSITIONS: Final[dict[CampaignStatus, frozenset[CampaignStatus]]] = {
    CampaignStatus.DRAFT: frozenset(
        {
            CampaignStatus.SCHEDULED,
            CampaignStatus.RUNNING,
            CampaignStatus.CANCELLED,
            CampaignStatus.ARCHIVED,
        }
    ),
    CampaignStatus.IDLE: frozenset(
        {
            CampaignStatus.SCHEDULED,
            CampaignStatus.RUNNING,
            CampaignStatus.CANCELLED,
            CampaignStatus.ARCHIVED,
        }
    ),
    CampaignStatus.SCHEDULED: frozenset(
        {
            CampaignStatus.RUNNING,
            CampaignStatus.CANCELLED,
            CampaignStatus.ARCHIVED,
        }
    ),
    CampaignStatus.RUNNING: frozenset(
        {
            CampaignStatus.COMPLETED,
            CampaignStatus.FAILED,
            CampaignStatus.CANCELLED,
        }
    ),
    CampaignStatus.PAUSED: frozenset(
        {
            CampaignStatus.COMPLETED,
            CampaignStatus.FAILED,
            CampaignStatus.CANCELLED,
        }
    ),
    CampaignStatus.COMPLETED: frozenset(
        {
            CampaignStatus.RUNNING,
            CampaignStatus.ARCHIVED,
        }
    ),
    CampaignStatus.FAILED: frozenset(
        {
            CampaignStatus.RUNNING,
            CampaignStatus.ARCHIVED,
        }
    ),
    CampaignStatus.CANCELLED: frozenset(
        {
            CampaignStatus.RUNNING,
            CampaignStatus.ARCHIVED,
        }
    ),
    CampaignStatus.ARCHIVED: frozenset(),
}


def normalize_status(value: str | CampaignStatus | None) -> CampaignStatus:
    if value is None:
        return CampaignStatus.DRAFT
    if isinstance(value, CampaignStatus):
        return value
    raw = str(value).strip().lower()
    try:
        return CampaignStatus(raw)
    except ValueError:
        raise ValueError(f"unknown campaign status: {value!r}") from None


def can_transition(
    from_state: str | CampaignStatus,
    to_state: str | CampaignStatus,
    *,
    force: bool = False,
) -> bool:
    if force:
        return normalize_status(from_state) != normalize_status(to_state)
    src = normalize_status(from_state)
    dst = normalize_status(to_state)
    if src == dst:
        return False
    return dst in _TRANSITIONS.get(src, frozenset())


def transition_error_message(
    from_state: str | CampaignStatus,
    to_state: str | CampaignStatus,
) -> str:
    src = normalize_status(from_state)
    dst = normalize_status(to_state)
    if src == dst:
        return f"Campaign already in status {src.value}"
    allowed = sorted(s.value for s in _TRANSITIONS.get(src, frozenset()))
    return (
        f"Cannot transition from {src.value} to {dst.value}; "
        f"allowed: {', '.join(allowed) or '(none)'}"
    )


def is_body_locked(status: str | CampaignStatus) -> bool:
    """Body fields mutable in draft/idle/cancelled (re-run prep after cancel)."""
    state = normalize_status(status)
    return state not in _BODY_MUTABLE


def allows_scheduled_metadata_only(status: str | CampaignStatus) -> bool:
    return normalize_status(status) == CampaignStatus.SCHEDULED


def is_running_like(status: str | CampaignStatus) -> bool:
    return normalize_status(status) in _LEGACY_AS_RUNNING


_DISPATCHABLE_FROM: Final[frozenset[CampaignStatus]] = frozenset(
    {
        CampaignStatus.DRAFT,
        CampaignStatus.IDLE,
        CampaignStatus.SCHEDULED,
        CampaignStatus.CANCELLED,
        CampaignStatus.COMPLETED,
        CampaignStatus.FAILED,
    }
)


def can_dispatch(status: str | CampaignStatus) -> bool:
    """True when a new fan-out dispatch is allowed (prevents double-dispatch)."""
    return normalize_status(status) in _DISPATCHABLE_FROM


def all_transition_pairs() -> list[tuple[CampaignStatus, CampaignStatus, bool]]:
    pairs: list[tuple[CampaignStatus, CampaignStatus, bool]] = []
    for src in CampaignStatus:
        for dst in CampaignStatus:
            if src == dst:
                continue
            pairs.append((src, dst, can_transition(src, dst)))
    return pairs
