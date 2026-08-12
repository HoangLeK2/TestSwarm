"""Scenario preview/run on device or via MCP session."""

from __future__ import annotations

import asyncio
import json
import logging
import importlib
import queue
import threading
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
    cancel_event: Optional["threading.Event"] = None,
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
    return run_scenario_task(device, scenario, on_step_done=on_step_done, cancel_event=cancel_event)


def _resolve_user_id_from_request(request: Request) -> Optional[str]:
    """Delegates to the unified auth context. Preserves the legacy return
    shape (Optional[str]) so existing callers don't need to change."""
    ctx = caller_auth_from_request(request)
    return ctx.user_id if ctx else None


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
        if body.account_group_id:
            acct_vars = await _resolve_account_group_vars(body.account_group_id, user_id)
        elif not base_vars.get("__ACCOUNT_ID__"):
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
        else:
            acct_vars = {}
        body.variables = {**base_vars, **acct_vars}


async def _execute_scenario_body(
    manager: DeviceManager,
    serial: str,
    body: ScenarioPreviewRequest,
    trace_source: str = "api.preview",
    user_id: Optional[str] = None,
):
    if not body.steps:
        return JSONResponse(
            {"error": "steps must be a non-empty array"},
            status_code=400,
        )
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
            manager, serial, body, trace_source="api.preview", user_id=user_id
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
        auth_ctx = caller_auth_from_request(request)
        user_id = auth_ctx.user_id if auth_ctx else None
        await _apply_preview_variables(
            body,
            serial,
            user_id,
            auth_ctx.org_id if auth_ctx else None,
        )

        cancel_event = threading.Event()
        _register_preview(serial, trace_id, cancel_event, user_id=user_id)

        q: queue.Queue[Dict[str, Any] | None] = queue.Queue()
        worker_done = threading.Event()

        def on_step_done(result: Dict[str, Any]) -> None:
            q.put(result)

        def run_in_thread() -> None:
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
                    cancel_event=cancel_event,
                )
                q.put({"_event": "done", **final})
            except Exception as exc:
                q.put({"_event": "error", "error": str(exc)})
            finally:
                worker_done.set()
                _unregister_preview(serial, trace_id)
                q.put(None)  # sentinel

        threading.Thread(target=run_in_thread, daemon=True).start()

        async def event_generator():
            total_steps = len(body.steps)
            yield f"data: {json.dumps({'event': 'start', 'trace_id': trace_id, 'total_steps': total_steps})}\n\n"
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
            manager, serial, body, trace_source="api.run", user_id=user_id
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
        )
        result = await loop.run_in_executor(None, fn)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return {"session_id": session_id, "device_id": device_id, **result}

    return router
