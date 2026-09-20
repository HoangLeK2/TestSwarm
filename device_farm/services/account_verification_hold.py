from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from db.models.account import Account

VerificationHoldPreset = Literal["one_week", "two_weeks", "custom"]

_PRESET_DAYS: dict[str, int] = {
    "one_week": 7,
    "two_weeks": 14,
}


class AccountVerificationHoldBody(BaseModel):
    preset: VerificationHoldPreset = Field(default="one_week")
    remind_at: datetime | None = None
    notify_web: bool = True
    notify_telegram: bool = True

    @model_validator(mode="after")
    def _custom_requires_remind_at(self) -> "AccountVerificationHoldBody":
        if self.preset == "custom" and self.remind_at is None:
            raise ValueError("custom verification hold requires remind_at")
        return self


class AccountVerificationHoldOut(BaseModel):
    preset: str
    remind_at: datetime
    notify_web: bool = True
    notify_telegram: bool = True
    created_at: datetime | None = None
    created_by_user_id: str | None = None


def resolve_verification_hold_reminder(
    body: AccountVerificationHoldBody,
    *,
    now: datetime | None = None,
) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if body.preset in _PRESET_DAYS:
        return base + timedelta(days=_PRESET_DAYS[body.preset])
    if body.remind_at is None:
        raise ValueError("custom verification hold requires remind_at")
    remind_at = body.remind_at
    if remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)
    if remind_at <= base:
        raise ValueError("verification hold remind_at must be in the future")
    return remind_at


def build_verification_hold_payload(
    body: AccountVerificationHoldBody,
    *,
    actor_user_id: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    created_at = now or datetime.now(timezone.utc)
    remind_at = resolve_verification_hold_reminder(body, now=created_at)
    return {
        "preset": body.preset,
        "remind_at": remind_at.isoformat(),
        "notify_web": body.notify_web,
        "notify_telegram": body.notify_telegram,
        "created_at": created_at.isoformat(),
        "created_by_user_id": actor_user_id,
    }


def get_verification_hold(account: Account) -> AccountVerificationHoldOut | None:
    metadata = account.account_metadata or {}
    raw = metadata.get("verification_hold")
    if not isinstance(raw, dict):
        return None
    remind_at_raw = raw.get("remind_at")
    if not remind_at_raw:
        return None
    try:
        remind_at = (
            remind_at_raw
            if isinstance(remind_at_raw, datetime)
            else datetime.fromisoformat(str(remind_at_raw))
        )
    except ValueError:
        return None
    created_at_raw = raw.get("created_at")
    created_at: datetime | None = None
    if created_at_raw:
        try:
            created_at = (
                created_at_raw
                if isinstance(created_at_raw, datetime)
                else datetime.fromisoformat(str(created_at_raw))
            )
        except ValueError:
            created_at = None
    return AccountVerificationHoldOut(
        preset=str(raw.get("preset") or "custom"),
        remind_at=remind_at,
        notify_web=bool(raw.get("notify_web", True)),
        notify_telegram=bool(raw.get("notify_telegram", True)),
        created_at=created_at,
        created_by_user_id=raw.get("created_by_user_id"),
    )


def set_verification_hold(account: Account, payload: dict[str, Any]) -> None:
    metadata = dict(account.account_metadata or {})
    metadata["verification_hold"] = payload
    account.account_metadata = metadata


def clear_verification_hold(account: Account) -> None:
    metadata = dict(account.account_metadata or {})
    if "verification_hold" in metadata:
        metadata.pop("verification_hold", None)
        account.account_metadata = metadata
