"""Apply campaign lifecycle transitions with audit + metrics (DF-T-04-007)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import Campaign
from db.models.enums import CampaignStatus
from services.campaign.events import emit_campaign_status_changed
from services.campaign.fsm import can_transition, normalize_status, transition_error_message
from services.campaign.errors import CampaignError


class CampaignInvalidTransitionError(CampaignError):
    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(
            transition_error_message(from_state, to_state),
            code="INVALID_TRANSITION",
        )
        self.from_state = from_state
        self.to_state = to_state


class CampaignLockedError(CampaignError):
    def __init__(self, message: str = "Campaign body immutable for current status") -> None:
        super().__init__(message, code="CAMPAIGN_LOCKED")


@dataclass(frozen=True, slots=True)
class TransitionResult:
    campaign_id: str
    from_status: str
    to_status: str
    changed: bool
    reason: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def assert_body_fields_mutable(
    row: Campaign,
    *,
    scenario_refs: object | None = None,
    vars: object | None = None,
    per_device_overrides: object | None = None,
) -> None:
    """Reject body mutations when campaign is not editable (AC-6)."""
    from services.campaign.fsm import allows_scheduled_metadata_only, is_body_locked

    if scenario_refs is None and vars is None and per_device_overrides is None:
        return

    state = normalize_status(row.status)
    if state in (CampaignStatus.DRAFT, CampaignStatus.IDLE, CampaignStatus.CANCELLED):
        return

    if allows_scheduled_metadata_only(state):
        if scenario_refs is not None or per_device_overrides is not None or vars is not None:
            raise CampaignLockedError(
                "Campaign body immutable when status is scheduled; only metadata may change"
            )
        return

    if is_body_locked(state):
        raise CampaignLockedError(
            f"Campaign body immutable when status is {state.value}"
        )


async def apply_campaign_transition(
    db: AsyncSession,
    row: Campaign,
    to_status: str | CampaignStatus,
    *,
    org_id: str,
    user_id: str | None = None,
    reason: str | None = None,
    force: bool = False,
) -> TransitionResult:
    """Transition campaign status with row lock and domain event."""
    from tenancy.context import use_tenant_scope

    with use_tenant_scope(org_id):
        locked = await db.execute(
            select(Campaign).where(Campaign.id == row.id).with_for_update()
        )
    current = locked.scalar_one_or_none()
    if current is None:
        from services.campaign.errors import CampaignNotFoundError

        raise CampaignNotFoundError()

    from_status = normalize_status(current.status)
    target = normalize_status(to_status)

    if from_status == target:
        return TransitionResult(
            campaign_id=current.id,
            from_status=from_status.value,
            to_status=target.value,
            changed=False,
            reason=reason,
        )

    if not can_transition(from_status, target, force=force):
        raise CampaignInvalidTransitionError(from_status.value, target.value)

    ts = _now()
    current.status = target.value
    current.updated_at = ts
    current.lock_version = int(getattr(current, "lock_version", 0) or 0) + 1

    if target == CampaignStatus.RUNNING and current.started_at is None:
        current.started_at = ts
    if target == CampaignStatus.COMPLETED:
        current.completed_at = ts
    if target == CampaignStatus.CANCELLED:
        current.cancelled_at = ts
    if from_status == CampaignStatus.CANCELLED and target == CampaignStatus.RUNNING:
        current.cancelled_at = None
    if target == CampaignStatus.RUNNING and from_status in (
        CampaignStatus.COMPLETED,
        CampaignStatus.FAILED,
    ):
        current.completed_at = None
    if target == CampaignStatus.ARCHIVED:
        current.deleted_at = ts

    await db.flush()

    await emit_campaign_status_changed(
        db,
        org_id=org_id,
        campaign_id=current.id,
        user_id=user_id,
        from_status=from_status.value,
        to_status=target.value,
        reason=reason,
        force=force,
    )

    return TransitionResult(
        campaign_id=current.id,
        from_status=from_status.value,
        to_status=target.value,
        changed=True,
        reason=reason,
    )


async def transition_campaign_for_org(
    db: AsyncSession,
    *,
    org_id: str,
    campaign_id: str,
    to_status: str | CampaignStatus,
    user_id: str | None = None,
    reason: str | None = None,
    force: bool = False,
) -> TransitionResult:
    from db.crud import campaign_entity as repo
    from services.campaign.errors import CampaignNotFoundError

    row = await repo.get_campaign_entity(db, campaign_id)
    if row is None or row.org_id != org_id:
        raise CampaignNotFoundError()
    return await apply_campaign_transition(
        db,
        row,
        to_status,
        org_id=org_id,
        user_id=user_id,
        reason=reason,
        force=force,
    )
