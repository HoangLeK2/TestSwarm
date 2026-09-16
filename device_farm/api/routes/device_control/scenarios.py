"""Scenario preview/run on device or via MCP session."""

from __future__ import annotations

import asyncio
import json
import logging
import importlib
import queue
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

# Keyed by (serial, trace_id) with owner user_id so cancel routes must match
# both the device and (optionally) the caller, preventing cross-device and
# cross-owner cancels that plain trace_id lookup allowed.
_ACTIVE_PREVIEWS: Dict[tuple, dict] = {}
_ACTIVE_PREVIEWS_LOCK = threading.Lock()


def _register_preview(
    serial: str,
    trace_id: str,
    event: "threading.Event",
    user_id: Optional[str] = None,
) -> None:
    with _ACTIVE_PREVIEWS_LOCK:
        _ACTIVE_PREVIEWS[(serial, trace_id)] = {
            "event": event,
            "user_id": user_id,
        }


def _unregister_preview(serial: str, trace_id: str) -> None:
    with _ACTIVE_PREVIEWS_LOCK:
        _ACTIVE_PREVIEWS.pop((serial, trace_id), None)


def _get_preview_entry(serial: str, trace_id: str) -> Optional[dict]:
    with _ACTIVE_PREVIEWS_LOCK:
        return _ACTIVE_PREVIEWS.get((serial, trace_id))


def _finish_preview_stream(
    serial: str,
    trace_id: str,
    event: "threading.Event",
    worker_done: "threading.Event",
    *,
    completed: bool,
) -> None:
    if not completed or not worker_done.is_set():
        event.set()
    if worker_done.is_set():
        _unregister_preview(serial, trace_id)


def cancel_all_previews_for_serial(
    serial: str,
    user_id: Optional[str] = None,
) -> int:
    """Signal cancel on every in-flight preview stream for a device.

    Used by interrupt/stop when the client has not yet captured trace_id from
    the SSE ``start`` event, or when cancel-by-trace_id returns 404.
    """
    cancelled = 0
    with _ACTIVE_PREVIEWS_LOCK:
        for (s, _tid), entry in list(_ACTIVE_PREVIEWS.items()):
            if s != serial:
                continue
            owner_id = entry.get("user_id")
            if owner_id and user_id and owner_id != user_id:
                continue
            entry["event"].set()
            cancelled += 1
    return cancelled
from api.auth import policy
from api.auth.context import AuthContext
from api.deps import caller_auth_from_request
from api.schemas.device_control import ScenarioPreviewRequest
from common.session_lock import SessionLockStore
from common.totp import account_metadata_value
from core.config import Config
from db import crud as repo
from db.database import AsyncSessionLocal
from db.crud.scenario_device_variable import get_scenario_device_variables
from common.variable_resolver import normalize_device_vars, normalize_variable_map
from runtime.core import DeviceManager
from tenancy.context import use_tenant_scope

log = logging.getLogger(__name__)
trace_log = importlib.import_module("structlog").get_logger("scenario_trace")


def run_scenario_on_device(
    manager: DeviceManager, serial: str, steps: List[Dict[str, Any]],
    on_step_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    variables: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    trace_source: str = "api.preview",
    user_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    cancel_event: Optional["threading.Event"] = None,
    scenario_registry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from tasks.scenario_task import run_scenario_task

    device = manager.get_device(serial)
    if not device:
        return {"error": f"Device {serial} not found"}
    if not steps:
        return {"error": "steps must be a non-empty array"}
    run_id = uuid4().hex
    scenario: Dict[str, Any] = {
        "instructions": "",
        "steps": steps,
        "variables": variables or {},
        "_trace_id": trace_id or f"scn-{run_id[:10]}",
        "_trace_source": trace_source,
        "_campaign_vars": {"__USER_ID__": str(user_id)} if user_id else {},
        "_run_hash_scope": run_id,
    }
    if execution_id:
        scenario["execution_id"] = execution_id
        scenario["run_id"] = execution_id
        scenario["_run_hash_scope"] = execution_id
    if scenario_registry:
        scenario["_scenario_registry"] = scenario_registry
    account_id = str((variables or {}).get("__ACCOUNT_ID__") or "").strip()
    if account_id:
        scenario["account_id"] = account_id
    from services.scenario_node_preflight import (
        preflight_scenario_node_capabilities,
        scenario_node_preflight_error_payload,
    )

    preflight = preflight_scenario_node_capabilities(device, scenario)
    if not preflight.ok:
        return scenario_node_preflight_error_payload(preflight)
    return run_scenario_task(device, scenario, on_step_done=on_step_done, cancel_event=cancel_event)


def _scenario_node_preflight_response(
    device: Any,
    scenario: Dict[str, Any],
) -> JSONResponse | None:
    from services.scenario_node_preflight import (
        preflight_scenario_node_capabilities,
        scenario_node_preflight_error_payload,
    )

    preflight = preflight_scenario_node_capabilities(device, scenario)
    if preflight.ok:
        return None
    return JSONResponse(
        scenario_node_preflight_error_payload(preflight),
        status_code=400,
    )


def _resolve_user_id_from_request(request: Request) -> Optional[str]:
    """Delegates to the unified auth context. Preserves the legacy return
    shape (Optional[str]) so existing callers don't need to change."""
    ctx = caller_auth_from_request(request)
    return ctx.user_id if ctx else None


def _requested_account_id(body: ScenarioPreviewRequest) -> str:
    return str((body.variables or {}).get("__ACCOUNT_ID__") or "").strip()


async def _create_account_login_stream_execution(
    *,
    serial: str,
    body: ScenarioPreviewRequest,
    account_id: str,
    auth_ctx: AuthContext | None,
    trace_id: str,
    db_enabled: bool,
) -> dict[str, str] | None:
    """Create durable history for account-console login streams.

    Generic preview-stream remains ephemeral. The account login dialog is the
    primary login surface, though, so when it names an account we create the
    execution before the phone is touched and pass that id into the direct
    runner.
    """
    account_id = str(account_id or "").strip()
    if not account_id:
        return None
    if not db_enabled or auth_ctx is None or not auth_ctx.org_id:
        return None

    from db.crud.device import get_device_by_serial
    from db.crud.execution import (
        add_device_to_execution,
        create_execution,
        upsert_execution_result,
    )
    from db.models.enums import ExecutionKind, ExecutionStatus
    from services.campaign.account_resolver import (
        AccountBindingError,
        validate_account_in_org,
    )

    async with AsyncSessionLocal() as db:
        with use_tenant_scope(auth_ctx.org_id):
            device = await get_device_by_serial(db, serial)
            if device is None or str(device.org_id or "") != str(auth_ctx.org_id):
                raise HTTPException(status_code=404, detail="Device not found")
            try:
                account = await validate_account_in_org(db, account_id, auth_ctx.org_id)
            except AccountBindingError as exc:
                raise HTTPException(
                    status_code=getattr(exc, "status", 404),
                    detail=str(exc),
                ) from exc

            started_at = datetime.now(timezone.utc)
            execution = await create_execution(
                db,
                run_type="account_login",
                kind=ExecutionKind.SESSION.value,
                organization_id=auth_ctx.org_id,
                campaign_id=None,
                scenario_id=body.scenario_id,
                user_id=auth_ctx.user_id,
                account_id=str(account.id),
                status=ExecutionStatus.RUNNING.value,
                meta={
                    "source": "account_login_dialog",
                    "trace_id": trace_id,
                    "step_count": len(body.steps or []),
                },
                device_config={"device_serial": serial},
            )
            execution.started_at = started_at
            await add_device_to_execution(db, execution.id, device.id)
            await upsert_execution_result(
                db,
                execution_id=execution.id,
                device_id=device.id,
                status="running",
                started_at=started_at,
            )
            await db.commit()
            return {"execution_id": str(execution.id), "device_id": str(device.id)}


async def _finish_account_login_stream_execution(
    execution_ctx: dict[str, str] | None,
    result: dict[str, Any],
    *,
    duration_s: float,
    cancelled: bool,
) -> None:
    if not execution_ctx:
        return

    from db.crud.execution import get_execution, upsert_execution_result
    from db.models.enums import ExecutionStatus
    from services.execution.step_store import (
        persist_execution_steps_from_results,
        slim_step_results,
    )

    execution_id = execution_ctx["execution_id"]
    device_id = execution_ctx["device_id"]
    step_results = [
        row for row in result.get("step_results", []) if isinstance(row, dict)
    ]
    success = bool(result.get("success"))
    status = (
        ExecutionStatus.CANCELLED.value
        if cancelled
        else ExecutionStatus.COMPLETED.value
        if success
        else ExecutionStatus.FAILED.value
    )
    result_status = (
        "passed" if status == ExecutionStatus.COMPLETED.value else "failed"
    )
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        execution = await get_execution(db, execution_id)
        if execution is None:
            return
        execution.status = status
        execution.finished_at = now
        if cancelled:
            execution.cancelled_at = now
            execution.cancel_signal_received_at = now
            execution.cancel_reason = result.get("failed_message") or "cancelled"
        await persist_execution_steps_from_results(
            db,
            execution_id=execution_id,
            step_results=step_results,
            default_ended_at=now,
            device_id=device_id,
        )
        await upsert_execution_result(
            db,
            execution_id=execution_id,
            device_id=device_id,
            status=result_status,
            passed_steps=slim_step_results(
                [r for r in step_results if r.get("ok", True)]
            ),
            failed_steps=slim_step_results(
                [r for r in step_results if not r.get("ok", True)]
            ),
            error_detail=(
                None
                if success
                else str(result.get("failed_message") or "step failed")
            ),
            run_time_sec=duration_s,
            finished_at=now,
        )
        await db.commit()


async def _resolve_account_group_vars(
    account_group_id: Optional[str],
    user_id: Optional[str],
) -> Dict[str, Any]:
    """Pick one account from the group and return the ``__ACCOUNT_*`` vars
    (including decrypted password) for a preview / test run.

    Advances the group's rotation state just like a real dispatch — so
    repeated "Run" clicks rotate through the pool rather than always hitting
    the same account. Returns an empty dict on any failure (group missing,
    empty pool, ownership mismatch) so the preview still runs, just without
    account variables.
    """
    if not account_group_id:
        return {}
    try:
        from db.crud.account_group import get_group, pick_next_batch
        from common.crypto import decrypt_password
    except Exception:
        return {}
    try:
        async with AsyncSessionLocal() as db:
            group = await get_group(db, account_group_id, user_id=user_id)
            if group is None:
                return {}
            accounts = await pick_next_batch(db, account_group_id, 1)
            if not accounts:
                await db.commit()
                return {}
            account = accounts[0]
            out = _preview_account_vars(account, decrypt_password)
            await db.commit()
            return out
    except Exception as exc:
        log.warning("preview account_group resolve failed: %s", exc)
        return {}


def _preview_account_vars(account: Any, decrypt_password: Callable[[Any], str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "__ACCOUNT_ID__": str(account.id),
        "__ACCOUNT_USERNAME__": account.username,
        "__ACCOUNT_DISPLAY_NAME__": account.display_name or "",
        "__ACCOUNT_PLATFORM__": account.platform,
    }
    if account.password_encrypted:
        try:
            out["__ACCOUNT_PASSWORD__"] = decrypt_password(account.password_encrypted)
        except Exception:
            # Keep the preview running; the executor will report an unresolved secret.
            out["__ACCOUNT_PASSWORD__"] = ""
    metadata = getattr(account, "account_metadata", None) or {}
    email = account_metadata_value(metadata, "email", "login_email", "account_email")
    if email:
        out["__ACCOUNT_EMAIL__"] = email
    totp_secret = account_metadata_value(
        metadata,
        "totp_secret",
        "two_factor_secret",
        "authenticator_secret",
        "otp_secret",
        "2fa_secret",
    )
    if totp_secret:
        out["__ACCOUNT_TOTP_SECRET__"] = totp_secret
    totp_code = account_metadata_value(
        metadata,
        "totp_code",
        "auth_code",
        "authentication_code",
        "two_factor_code",
    )
    if totp_code:
        out["__ACCOUNT_TOTP_CODE__"] = totp_code
    return out


async def _resolve_primary_device_account_vars(
    serial_or_device_id: str,
    user_id: Optional[str],
    platform: str,
) -> Dict[str, Any]:
    """Resolve the deterministic account already assigned to this preview device."""
    try:
        from common.crypto import decrypt_password
        from db.crud.account import get_primary_account_for_device
        from db.crud.device import get_device, get_device_by_serial
    except Exception:
        return {}
    try:
        async with AsyncSessionLocal() as db:
            device = await get_device_by_serial(db, serial_or_device_id)
            if not device:
                device = await get_device(db, serial_or_device_id)
            if not device:
                return {}
            if user_id and getattr(device, "user_id", None) != user_id:
                return {}
            account = await get_primary_account_for_device(
                db,
                device.id,
                platform,
            )
            if not account:
                return {}
            return _preview_account_vars(account, decrypt_password)
    except Exception as exc:
        log.warning("preview primary account resolve failed: %s", exc)
        return {}


async def _resolve_linked_account_vars(
    serial_or_device_id: str,
    account_id: str,
) -> Dict[str, Any]:
    """Resolve credentials for one explicitly requested account on this device.

    The account must already be linked to the device. Running a login on a
    phone the account was never attached to is what the caller almost never
    means, and the account the *device* happens to carry would silently take
    its place — so an unlinked account resolves to nothing and the login step
    fails on an unresolved secret instead of signing in as somebody else.

    Scoped by org, not by ``user_id``: the account console is org-wide, so the
    phone an account is attached to is regularly one a teammate registered.
    Device and Account are both ``TenantScopedModel``, so the caller's tenant
    context already filters both lookups — an owner check on top of that would
    only refuse a device the operator is allowed to see.
    """
    try:
        from common.crypto import decrypt_password
        from db.crud.account import list_device_accounts
        from db.crud.device import get_device, get_device_by_serial
    except Exception:
        return {}
    try:
        async with AsyncSessionLocal() as db:
            device = await get_device_by_serial(db, serial_or_device_id)
            if not device:
                device = await get_device(db, serial_or_device_id)
            if not device:
                return {}
            link = next(
                (
                    row
                    for row in await list_device_accounts(db, device.id)
                    if str(row.account_id) == str(account_id)
                ),
                None,
            )
            if link is None or link.account is None:
                log.warning(
                    "preview account %s is not linked to device %s — no credentials injected",
                    account_id,
                    serial_or_device_id,
                )
                return {}
            return _preview_account_vars(link.account, decrypt_password)
    except Exception as exc:
        log.warning("preview linked account resolve failed: %s", exc)
        return {}


async def _resolve_device_runtime_vars(
    serial_or_device_id: str,
    user_id: Optional[str],
    scenario_id: Optional[str] = None,
    inline_device_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    inline_vars = normalize_device_vars(inline_device_vars or {})
    if not scenario_id:
        return inline_vars
    try:
        from db.crud.device import get_device, get_device_by_serial
    except Exception:
        return {}
    try:
        async with AsyncSessionLocal() as db:
            device = await get_device_by_serial(db, serial_or_device_id)
            if not device:
                device = await get_device(db, serial_or_device_id)
            if not device:
                return {}
            if user_id and getattr(device, "user_id", None) != user_id:
                return {}
            raw = await get_scenario_device_variables(db, scenario_id, device.id)
            db_vars = normalize_device_vars(raw)
            # Persisted vars win over inline drafts so a save-before-run is not
            # shadowed by stale UI state. Unsaved device-var edits require save.
            return {**inline_vars, **db_vars}
    except Exception as exc:
        log.warning("preview device vars resolve failed: %s", exc)
        return inline_vars


async def _resolve_scenario_scope_vars(
    scenario_id: str,
    user_id: Optional[str],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Load campaign + scenario variable maps from DB for preview/run."""
    try:
        async with AsyncSessionLocal() as db:
            scenario = await repo.get_scenario(db, scenario_id)
            if not scenario:
                return {}, {}
            campaign = await repo.get_campaign(db, scenario.campaign_id)
            if user_id and campaign and getattr(campaign, "user_id", None) != user_id:
                return {}, {}
            campaign_vars = normalize_variable_map(
                (campaign.variables or {}) if campaign else {}
            )
            scenario_vars = normalize_variable_map(scenario.variables or {})
            return campaign_vars, scenario_vars
    except Exception as exc:
        log.warning("preview scenario vars resolve failed: %s", exc)
        return {}, {}


def merge_preview_variable_layers(
    *,
    client_vars: Optional[Dict[str, Any]] = None,
    campaign_vars: Optional[Dict[str, Any]] = None,
    scenario_vars: Optional[Dict[str, Any]] = None,
    device_vars: Optional[Dict[str, Any]] = None,
    account_vars: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge variable scopes for preview/run (lowest → highest priority)."""
    return {
        **(client_vars or {}),
        **(campaign_vars or {}),
        **(scenario_vars or {}),
        **(device_vars or {}),
        **(account_vars or {}),
    }


async def _apply_preview_variables(
    body: ScenarioPreviewRequest,
    serial_or_device_id: str,
    user_id: Optional[str],
    org_id: Optional[str] = None,
) -> None:
    """Resolve DB-backed vars into ``body.variables`` (mutates *body* in place)."""
    with use_tenant_scope(org_id):
        campaign_vars: Dict[str, Any] = {}
        scenario_vars: Dict[str, Any] = {}
        if body.scenario_id:
            campaign_vars, scenario_vars = await _resolve_scenario_scope_vars(
                body.scenario_id,
                user_id,
            )
        device_vars = await _resolve_device_runtime_vars(
            serial_or_device_id,
            user_id,
            body.scenario_id,
            body.scenario_device_vars,
        )
        base_vars = merge_preview_variable_layers(
            client_vars=body.variables,
            campaign_vars=campaign_vars,
            scenario_vars=scenario_vars,
            device_vars=device_vars,
            account_vars={},
        )
        requested_account_id = str(base_vars.get("__ACCOUNT_ID__") or "").strip()
        if body.account_group_id:
            acct_vars = await _resolve_account_group_vars(body.account_group_id, user_id)
        elif requested_account_id:
            # Caller named the account (account console "Đăng nhập", per-account
            # test runs). Without this the password never resolves and the run
            # silently logs in as nobody.
            acct_vars = await _resolve_linked_account_vars(
                serial_or_device_id,
                requested_account_id,
            )
        else:
            platform = str(
                base_vars.get("__ACCOUNT_PLATFORM__")
                or base_vars.get("__PLATFORM__")
                or "facebook"
            ).strip().lower()
            acct_vars = await _resolve_primary_device_account_vars(
                serial_or_device_id,
                user_id,
                platform,
            )
        body.variables = {**base_vars, **acct_vars}


def _collect_preview_scenario_refs(
    steps: List[Dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect org-scenario ids referenced by ad-hoc preview payloads."""
    from services.scenario_dsl.ref_cache import extract_run_scenario_id
    from services.scenario_dsl.step_tree import iter_authored_steps

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for authored in iter_authored_steps(steps):
        ref_id = extract_run_scenario_id(authored.step)
        if not ref_id or ref_id in seen:
            continue
        seen.add(ref_id)
        refs.append({"scenario_id": ref_id})
    return refs


async def _build_preview_scenario_registry(
    body: ScenarioPreviewRequest,
    org_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Load nested org scenarios so preview-stream can run run_scenario steps."""
    if not org_id:
        return None
    refs = _collect_preview_scenario_refs(body.steps)
    if not refs:
        return None
    try:
        from services.campaign.execution_runtime import build_org_scenario_registry

        async with AsyncSessionLocal() as db:
            with use_tenant_scope(org_id):
                return await build_org_scenario_registry(db, org_id, refs)
    except Exception as exc:
        log.warning("preview scenario registry resolve failed: %s", exc)
        return None


async def _execute_scenario_body(
    manager: DeviceManager,
    serial: str,
    body: ScenarioPreviewRequest,
    trace_source: str = "api.preview",
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
):
    if not body.steps:
        return JSONResponse(
            {"error": "steps must be a non-empty array"},
            status_code=400,
        )
    device = manager.get_device(serial)
    if not device:
        return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
    scenario = {
        "steps": body.steps,
        "variables": body.variables or {},
    }
    scenario_registry = await _build_preview_scenario_registry(body, org_id)
    if scenario_registry:
        scenario["_scenario_registry"] = scenario_registry
    preflight_response = _scenario_node_preflight_response(device, scenario)
    if preflight_response is not None:
        return preflight_response
    loop = asyncio.get_running_loop()
    import functools
    trace_id = f"scn-{uuid4().hex[:10]}"
    trace_log.info(
        "scenario_request",
        trace_id=trace_id,
        serial=serial,
        source=trace_source,
        total_steps=len(body.steps),
    )
    fn = functools.partial(
        run_scenario_on_device,
        manager,
        serial,
        body.steps,
        None,
        body.variables,
        trace_id,
        trace_source,
        user_id,
        scenario_registry=scenario_registry,
    )
    result = await loop.run_in_executor(None, fn)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


def build_scenarios_router(
    manager: DeviceManager,
    config: Config,
    session_store: SessionLockStore,
) -> APIRouter:
    router = APIRouter()

    @router.post("/devices/{serial}/scenario/preview")
    async def api_scenario_preview(serial: str, body: ScenarioPreviewRequest, request: Request):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        auth_ctx = caller_auth_from_request(request)
        user_id = auth_ctx.user_id if auth_ctx else None
        await _apply_preview_variables(
            body,
            serial,
            user_id,
            auth_ctx.org_id if auth_ctx else None,
        )
        return await _execute_scenario_body(
            manager,
            serial,
            body,
            trace_source="api.preview",
            user_id=user_id,
            org_id=auth_ctx.org_id if auth_ctx else None,
        )

    @router.post("/devices/{serial}/scenario/preview-stream")
    async def api_scenario_preview_stream(serial: str, body: ScenarioPreviewRequest, request: Request):
        """
        SSE endpoint: streams step results as they complete.
        Each event is a JSON object with the step result.
        Final event has type "done" with full summary.
        """
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        if not body.steps:
            return JSONResponse({"error": "steps must be a non-empty array"}, status_code=400)
        trace_id = f"scn-{uuid4().hex[:10]}"
        trace_log.info(
            "scenario_stream_request",
            trace_id=trace_id,
            serial=serial,
            source="api.preview_stream",
            total_steps=len(body.steps),
        )
        account_login_account_id = _requested_account_id(body)
        auth_ctx = caller_auth_from_request(request)
        user_id = auth_ctx.user_id if auth_ctx else None
        await _apply_preview_variables(
            body,
            serial,
            user_id,
            auth_ctx.org_id if auth_ctx else None,
        )
        scenario_registry = await _build_preview_scenario_registry(
            body,
            auth_ctx.org_id if auth_ctx else None,
        )
        preflight_response = _scenario_node_preflight_response(
            device,
            {
                "steps": body.steps,
                "variables": body.variables or {},
                **(
                    {"_scenario_registry": scenario_registry}
                    if scenario_registry
                    else {}
                ),
            },
        )
        if preflight_response is not None:
            return preflight_response

        execution_ctx = await _create_account_login_stream_execution(
            serial=serial,
            body=body,
            account_id=account_login_account_id,
            auth_ctx=auth_ctx,
            trace_id=trace_id,
            db_enabled=bool(getattr(config.database, "enabled", False)),
        )
        cancel_event = threading.Event()
        _register_preview(serial, trace_id, cancel_event, user_id=user_id)

        q: queue.Queue[Dict[str, Any] | None] = queue.Queue()
        worker_done = threading.Event()
        main_loop = asyncio.get_running_loop()

        def on_step_done(result: Dict[str, Any]) -> None:
            q.put(result)

        def run_in_thread() -> None:
            started_mono = time.monotonic()

            def finalize(result: Dict[str, Any]) -> None:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        _finish_account_login_stream_execution(
                            execution_ctx,
                            result,
                            duration_s=time.monotonic() - started_mono,
                            cancelled=cancel_event.is_set(),
                        ),
                        main_loop,
                    )
                    future.result(timeout=30)
                except Exception:
                    log.exception(
                        "preview-stream execution finalize failed trace_id=%s",
                        trace_id,
                    )

            try:
                final = run_scenario_on_device(
                    manager,
                    serial,
                    body.steps,
                    on_step_done=on_step_done,
                    variables=body.variables,
                    trace_id=trace_id,
                    trace_source="api.preview_stream",
                    user_id=user_id,
                    execution_id=(
                        execution_ctx["execution_id"] if execution_ctx else None
                    ),
                    cancel_event=cancel_event,
                    scenario_registry=scenario_registry,
                )
                finalize(final)
                q.put({"_event": "done", **final})
            except Exception as exc:
                finalize(
                    {
                        "success": False,
                        "failed_message": str(exc),
                        "step_results": [],
                    }
                )
                q.put({"_event": "error", "error": str(exc)})
            finally:
                worker_done.set()
                _unregister_preview(serial, trace_id)
                q.put(None)  # sentinel

        threading.Thread(target=run_in_thread, daemon=True).start()

        async def event_generator():
            total_steps = len(body.steps)
            start_payload = {
                "event": "start",
                "trace_id": trace_id,
                "total_steps": total_steps,
            }
            if execution_ctx:
                start_payload["execution_id"] = execution_ctx["execution_id"]
            yield f"data: {json.dumps(start_payload)}\n\n"
            completed = False
            try:
                while True:
                    if await request.is_disconnected():
                        cancel_event.set()
                        break
                    try:
                        item = await asyncio.get_event_loop().run_in_executor(None, q.get, True, 0.1)
                    except queue.Empty:
                        continue
                    if item is None:
                        completed = True
                        break
                    if "_event" in item:
                        evt_type = item.pop("_event")
                        yield f"data: {json.dumps({'event': evt_type, **item})}\n\n"
                    else:
                        yield f"data: {json.dumps({'event': 'step_done', **item})}\n\n"
            finally:
                _finish_preview_stream(
                    serial,
                    trace_id,
                    cancel_event,
                    worker_done,
                    completed=completed,
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/devices/{serial}/scenario/preview-stream/{trace_id}/cancel")
    async def api_scenario_preview_stream_cancel(serial: str, trace_id: str, request: Request):
        entry = _get_preview_entry(serial, trace_id)
        if entry is None:
            return JSONResponse(
                {"error": "trace not found or already finished"}, status_code=404
            )
        # Owner check: only the user who started the stream (or an unauth
        # caller when the stream had no owner) may cancel.
        owner_id = entry.get("user_id")
        caller_id = _resolve_user_id_from_request(request)
        if owner_id and caller_id != owner_id:
            return JSONResponse(
                {"error": "not owner of this trace"}, status_code=403
            )
        entry["event"].set()
        device = manager.get_device(serial)
        if device is not None:
            from tasks.scenario_task import force_clear_scenario_busy

            force_clear_scenario_busy(device)
        return {"ok": True, "serial": serial, "trace_id": trace_id, "cancelled": True}

    @router.post("/devices/{serial}/scenario/run")
    async def api_scenario_run(serial: str, body: ScenarioPreviewRequest, request: Request):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        auth_ctx = caller_auth_from_request(request)
        user_id = auth_ctx.user_id if auth_ctx else None
        await _apply_preview_variables(
            body,
            serial,
            user_id,
            auth_ctx.org_id if auth_ctx else None,
        )
        return await _execute_scenario_body(
            manager,
            serial,
            body,
            trace_source="api.run",
            user_id=user_id,
            org_id=auth_ctx.org_id if auth_ctx else None,
        )

    @router.post("/sessions/{session_id}/scenario/run")
    async def api_sessions_scenario_run(session_id: str, body: ScenarioPreviewRequest, request: Request):
        ctx = caller_auth_from_request(request)
        if ctx is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        if not config.database.enabled:
            return JSONResponse(
                {"error": "Session API requires database (multi-user) mode"},
                status_code=501,
            )
        try:
            device_id = await policy.assert_owns_session(ctx, session_id)
        except HTTPException as exc:
            return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
        except Exception:
            log.exception("sessions_scenario_run: assert_owns_session infra error")
            return JSONResponse(
                {"error": "Backend unavailable"}, status_code=503
            )
        if not device_id:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        caller_id = ctx.user_id
        await _apply_preview_variables(body, device_id, caller_id, ctx.org_id)
        if not body.steps:
            return JSONResponse(
                {"error": "steps must be a non-empty array"},
                status_code=400,
            )
        loop = asyncio.get_running_loop()
        import functools
        trace_id = f"scn-{uuid4().hex[:10]}"
        trace_log.info(
            "scenario_session_request",
            trace_id=trace_id,
            serial=device_id,
            source="api.session_run",
            total_steps=len(body.steps),
            session_id=session_id,
        )
        scenario_registry = await _build_preview_scenario_registry(body, ctx.org_id)
        fn = functools.partial(
            run_scenario_on_device,
            manager,
            device_id,
            body.steps,
            None,
            body.variables,
            trace_id,
            "api.session_run",
            caller_id,
            scenario_registry=scenario_registry,
        )
        result = await loop.run_in_executor(None, fn)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return {"session_id": session_id, "device_id": device_id, **result}

    return router
