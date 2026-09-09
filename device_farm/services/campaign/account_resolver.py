"""Campaign account binding resolver (DF-T-04-009)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.account import get_accounts_by_ids, get_primary_accounts_for_devices
from db.crud.account_group import get_group, pick_next_batch
from db.models.account import Account, DeviceAccount
from services.social_ext.contract import SOCIAL_ACCOUNT_BOUND_STEP_TYPES
from db.models.campaign import Campaign
from db.models.enums import AccountState
from services.org_scenario_validation.step_index import OrgStepIndex
from services.platform_session_guard import DEFAULT_PLATFORM
from services.scenario_dsl.step_registry import StepRegistry

log = logging.getLogger(__name__)

_ACCOUNT_VAR_KEYS = frozenset(
    {"__ACCOUNT_ID__", "__ACCOUNT_USERNAME__", "__ACCOUNT_DISPLAY_NAME__", "__ACCOUNT_PLATFORM__"}
)

# Social steps that mutate state or need credentials (FR-04-20). Read-only crawl/UI
# (extract, social_open_comments, generic tap/wait) is intentionally excluded.
_ACCOUNT_BINDING_TYPE_HINTS = (
    "login",
    ".auth",
    ".create",
    ".follow",
    ".send",
    ".share",
)
# Sourced from the neutral vocabulary so a new platform inherits this for free.
_ACCOUNT_BINDING_EXACT_TYPES = frozenset(
    SOCIAL_ACCOUNT_BOUND_STEP_TYPES | {"lease_source_target"}
)


class AccountBindingError(Exception):
    def __init__(self, message: str, *, code: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class ResolvedDeviceAccount:
    account_id: str | None
    account_vars: dict[str, Any]
    unavailable: bool = False
    failure_reason: str | None = None
    session_guard: dict[str, Any] | None = None


def account_to_vars(account: Account) -> dict[str, Any]:
    """Opaque account reference vars — no credential fields."""
    return {
        "__ACCOUNT_ID__": str(account.id),
        "__ACCOUNT_USERNAME__": account.username,
        "__ACCOUNT_DISPLAY_NAME__": account.display_name or "",
        "__ACCOUNT_PLATFORM__": account.platform,
    }


def campaign_has_account_binding(campaign: Campaign) -> bool:
    if getattr(campaign, "account_group_id", None):
        return True
    if getattr(campaign, "scenario_account_id", None):
        return True
    per_device = getattr(campaign, "per_device_accounts", None) or {}
    return bool(per_device)


def _social_write_requires_account_binding(step_type: str) -> bool:
    """True when step type implies login or a mutating social action."""
    t = (step_type or "").lower()
    if not t:
        return False
    return t in _ACCOUNT_BINDING_EXACT_TYPES or any(
        hint in t for hint in _ACCOUNT_BINDING_TYPE_HINTS
    )


def _step_requires_account(step: dict) -> bool:
    stype = str(step.get("type") or "")
    if not stype:
        return False
    reg = StepRegistry.get(stype)
    if reg is not None:
        if reg.requires_account:
            return True
        schema = reg.schema or {}
        if schema.get("requires_account"):
            return True
    if _social_write_requires_account_binding(stype):
        return True
    return _step_references_account_vars(step)


def scenario_requires_account(steps: list[dict]) -> bool:
    """Whether campaign must bind account_group / scenario_account before dispatch.

    Aligns with preview account guard: login, explicit __ACCOUNT_* refs, and
    mutating social steps — not read-only Facebook crawl/UI.
    """
    if not steps:
        return False
    idx = OrgStepIndex.build(steps)
    return any(_step_requires_account(step) for step, _, _ in idx.entries)


def _step_references_account_vars(step: dict) -> bool:
    config = step.get("config")
    if isinstance(config, dict):
        blob = str(config)
    else:
        skip = frozenset({"steps", "then", "else", "branches"})
        flat = {k: v for k, v in step.items() if k not in skip}
        blob = str(flat)
    return any(key in blob for key in _ACCOUNT_VAR_KEYS)


async def load_pinned_scenario_steps(
    db: AsyncSession,
    campaign: Campaign,
    org_id: str,
) -> list[dict]:
    from db.crud.campaign_entity import loaded_org_scenario_refs

    refs = loaded_org_scenario_refs(campaign)
    if not refs:
        return []
    from db.crud import org_scenario as org_scenario_repo

    ordered = sorted(refs, key=lambda r: int(r.order_index or 0))
    scenario_ids = [ref.org_scenario_id for ref in ordered]
    bodies = await org_scenario_repo.get_org_scenario_bodies_by_ids(db, org_id, scenario_ids)
    body_map = {scenario_id: body for scenario_id, _kind, body in bodies}
    steps: list[dict] = []
    for ref in ordered:
        body = body_map.get(ref.org_scenario_id) or {}
        if isinstance(body, dict):
            raw = body.get("steps") or []
            if isinstance(raw, list):
                steps.extend(raw)
    return steps


async def assert_dispatch_account_guard(
    db: AsyncSession,
    *,
    campaign: Campaign,
    org_id: str,
) -> None:
    """Account availability is resolved per device during fan-out."""
    return None


async def validate_account_in_org(
    db: AsyncSession,
    account_id: str,
    org_id: str,
) -> Account:
    accounts = await get_accounts_by_ids(db, [account_id], org_id=org_id)
    account = accounts.get(account_id)
    if account is None:
        raise AccountBindingError(
            "Account not found",
            code="ACCOUNT_NOT_FOUND",
            details={"account_id": account_id},
        )
    return account


async def validate_account_group_in_org(
    db: AsyncSession,
    group_id: str,
    org_id: str,
) -> None:
    group = await get_group(db, group_id)
    if group is None or group.org_id != org_id:
        raise AccountBindingError(
            "Account group not found",
            code="ACCOUNT_NOT_FOUND",
            details={"account_group_id": group_id},
        )


def _account_is_dispatchable(account: Account, *, now: datetime | None = None) -> bool:
    ts = now or datetime.now(timezone.utc)
    if account.state != AccountState.ACTIVE.value:
        return False
    cooldown = account.cooldown_until
    if cooldown is not None and cooldown > ts:
        return False
    return True


def _resolve_account_row(
    account: Account | None,
    *,
    org_id: str,
    now: datetime,
) -> ResolvedDeviceAccount:
    if account is None or account.org_id != org_id:
        return ResolvedDeviceAccount(
            account_id=None,
            account_vars={},
            unavailable=True,
            failure_reason="account_unavailable",
        )
    if not _account_is_dispatchable(account, now=now):
        return ResolvedDeviceAccount(
            account_id=str(account.id),
            account_vars={},
            unavailable=True,
            failure_reason="account_unavailable",
        )
    return ResolvedDeviceAccount(
        account_id=str(account.id),
        account_vars=account_to_vars(account),
    )


async def revalidate_persisted_account(
    db: AsyncSession,
    *,
    account_id: str | None,
    org_id: str,
    required: bool = False,
) -> ResolvedDeviceAccount:
    """Revalidate the exact account snapshotted onto a queued execution."""
    if not account_id:
        return ResolvedDeviceAccount(
            account_id=None,
            account_vars={},
            unavailable=required,
            failure_reason="account_unavailable" if required else None,
        )
    now = datetime.now(timezone.utc)
    rows = await get_accounts_by_ids(db, [account_id], org_id=org_id)
    return _resolve_account_row(
        rows.get(account_id),
        org_id=org_id,
        now=now,
    )


async def resolve_accounts_for_devices(
    db: AsyncSession,
    *,
    campaign: Campaign,
    org_id: str,
    device_ids: list[str],
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, ResolvedDeviceAccount]:
    """Resolve the effective account for each campaign device on ``platform``."""
    if not device_ids:
        return {}

    now = datetime.now(timezone.utc)
    requires_account = scenario_requires_account(
        await load_pinned_scenario_steps(db, campaign, org_id)
    )

    per_device_accounts = {
        str(device_id): str(account_id)
        for device_id, account_id in (
            getattr(campaign, "per_device_accounts", None) or {}
        ).items()
        if device_id and account_id
    }
    explicit_account_ids: list[str] = []
    explicit_account_ids.extend(per_device_accounts.values())
    scenario_account_id = getattr(campaign, "scenario_account_id", None)
    if scenario_account_id:
        explicit_account_ids.append(str(scenario_account_id))
    explicit_accounts = (
        await get_accounts_by_ids(db, explicit_account_ids, org_id=org_id)
        if explicit_account_ids
        else {}
    )

    out: dict[str, ResolvedDeviceAccount] = {}

    for device_id in device_ids:
        account_id = per_device_accounts.get(str(device_id))
        if not account_id:
            continue
        out[device_id] = _resolve_account_row(
            explicit_accounts.get(account_id),
            org_id=org_id,
            now=now,
        )

    remaining_device_ids = [
        device_id for device_id in device_ids if device_id not in out
    ]

    account_group_id = getattr(campaign, "account_group_id", None)
    if account_group_id and remaining_device_ids:
        accounts = await pick_next_batch(
            db, str(account_group_id), len(remaining_device_ids)
        )
        granted = len(accounts)
        for index, device_id in enumerate(remaining_device_ids):
            if index < granted:
                out[device_id] = _resolve_account_row(
                    accounts[index],
                    org_id=org_id,
                    now=now,
                )
            else:
                out[device_id] = ResolvedDeviceAccount(
                    account_id=None,
                    account_vars={},
                    unavailable=True,
                    failure_reason="account_unavailable",
                )
        return out

    if scenario_account_id and remaining_device_ids:
        resolved = _resolve_account_row(
            explicit_accounts.get(str(scenario_account_id)),
            org_id=org_id,
            now=now,
        )
        for device_id in remaining_device_ids:
            out[device_id] = resolved
        return out

    primary_accounts = await get_primary_accounts_for_devices(
        db,
        remaining_device_ids,
        platform,
    )
    missing_primary_ids = [
        device_id for device_id in remaining_device_ids if device_id not in primary_accounts
    ]
    if missing_primary_ids:
        rows = (
            await db.execute(
                select(DeviceAccount.device_id, Account)
                .join(Account, Account.id == DeviceAccount.account_id)
                .where(
                    DeviceAccount.device_id.in_(missing_primary_ids),
                    Account.org_id == org_id,
                    Account.platform == platform,
                    Account.state == AccountState.ACTIVE.value,
                )
                .order_by(DeviceAccount.assigned_at)
            )
        ).all()
        accounts_by_device: dict[str, list[Account]] = {}
        for device_id, account in rows:
            accounts_by_device.setdefault(str(device_id), []).append(account)
        for device_id, linked_accounts in accounts_by_device.items():
            if len(linked_accounts) == 1:
                primary_accounts[device_id] = linked_accounts[0]

    for device_id in remaining_device_ids:
        account = primary_accounts.get(device_id)
        if account is None and not requires_account:
            out[device_id] = ResolvedDeviceAccount(account_id=None, account_vars={})
            continue
        out[device_id] = _resolve_account_row(
            account,
            org_id=org_id,
            now=now,
        )

    return out


async def validate_bind_payload(
    db: AsyncSession,
    *,
    org_id: str,
    account_group_id: str | None = None,
    scenario_account_id: str | None = None,
    per_device_accounts: dict[str, str] | None = None,
) -> None:
    if account_group_id:
        await validate_account_group_in_org(db, account_group_id, org_id)
    ids: list[str] = []
    if scenario_account_id:
        ids.append(scenario_account_id)
    ids.extend(str(v) for v in (per_device_accounts or {}).values() if v)
    if not ids:
        return
    found = await get_accounts_by_ids(db, ids, org_id=org_id)
    for account_id in ids:
        if account_id not in found:
            raise AccountBindingError(
                "Account not found",
                code="ACCOUNT_NOT_FOUND",
                details={"account_id": account_id},
            )
