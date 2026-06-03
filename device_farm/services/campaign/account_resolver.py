"""Campaign account binding resolver (DF-T-04-009)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.account import get_accounts_by_ids
from db.crud.account_group import get_group, pick_next_batch
from db.models.account import Account
from db.models.campaign import Campaign
from db.models.enums import AccountState
from services.org_scenario_validation.step_index import OrgStepIndex
from services.scenario_dsl.step_registry import StepRegistry

log = logging.getLogger(__name__)

_ACCOUNT_VAR_KEYS = frozenset(
    {"__ACCOUNT_ID__", "__ACCOUNT_USERNAME__", "__ACCOUNT_DISPLAY_NAME__", "__ACCOUNT_PLATFORM__"}
)

# Social steps that mutate state or need credentials (FR-04-20). Read-only crawl/UI
# (extract, tap_fb_comment_button, generic tap/wait) is intentionally excluded.
_ACCOUNT_BINDING_TYPE_HINTS = (
    "login",
    ".auth",
    ".create",
    ".follow",
    ".send",
    ".share",
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
    return any(hint in t for hint in _ACCOUNT_BINDING_TYPE_HINTS)


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
    """Fail before fan-out when scenarios need account but campaign has no binding."""
    if campaign_has_account_binding(campaign):
        return
    steps = await load_pinned_scenario_steps(db, campaign, org_id)
    if not scenario_requires_account(steps):
        return
    raise AccountBindingError(
        "Scenario requires account but campaign has no account binding; "
        "set account_group_id or scenario_account_id",
        code="ACCOUNT_NOT_BOUND",
        details={"hint": "khai báo account_group hoặc scenario_account_id"},
    )


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


async def resolve_accounts_for_devices(
    db: AsyncSession,
    *,
    campaign: Campaign,
    org_id: str,
    device_ids: list[str],
) -> dict[str, ResolvedDeviceAccount]:
    """Resolve effective account per device using bind precedence.

    DB round-trips: at most 1 batch account SELECT + 1 pick_next_batch (group).
    """
    if not device_ids:
        return {}

    per_device_map = dict(getattr(campaign, "per_device_accounts", None) or {})
    group_id = getattr(campaign, "account_group_id", None)
    shared_id = getattr(campaign, "scenario_account_id", None)
    now = datetime.now(timezone.utc)

    devices_for_group: list[str] = []
    if group_id:
        devices_for_group = [d for d in device_ids if d not in per_device_map]

    ids_to_load: set[str] = set()
    for device_id in device_ids:
        override_id = per_device_map.get(device_id)
        if override_id:
            ids_to_load.add(str(override_id))
    if shared_id and not group_id:
        ids_to_load.add(str(shared_id))

    account_rows = await get_accounts_by_ids(db, list(ids_to_load), org_id=org_id)

    group_accounts: list[Account] = []
    if group_id and devices_for_group:
        group_accounts = await pick_next_batch(db, group_id, len(devices_for_group))
    group_iter = iter(group_accounts)

    out: dict[str, ResolvedDeviceAccount] = {}
    for device_id in device_ids:
        override_id = per_device_map.get(device_id)
        account: Account | None = None

        if override_id:
            account = account_rows.get(str(override_id))
            out[device_id] = _resolve_account_row(account, org_id=org_id, now=now)
            continue

        if group_id and device_id in devices_for_group:
            account = next(group_iter, None)
            if account is None:
                out[device_id] = ResolvedDeviceAccount(account_id=None, account_vars={})
            else:
                out[device_id] = _resolve_account_row(account, org_id=org_id, now=now)
            continue

        if shared_id:
            account = account_rows.get(str(shared_id))
            out[device_id] = _resolve_account_row(account, org_id=org_id, now=now)
            continue

        out[device_id] = ResolvedDeviceAccount(account_id=None, account_vars={})

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
