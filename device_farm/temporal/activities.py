

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable

from temporalio import activity

from temporal.trace import activity_log_context, trace_log
from temporal.shared import (
    DeviceActionBatchInput,
    DeviceActionBatchResult,
    DeviceActionInput,
    ElementCheckInput,
    ElementCheckResult,
    ConditionCheckInput,
    LegacyConditionCheckInput,
    ExtractInput,
    ExtractResult,
    SaveExtractionInput,
    StepResult,
)
from services.extraction_usecase import (
    persist_data_items,
    resolve_comment_parent_hash,
    update_parent_stats_if_available,
)
from services.execution.dsl_runtime import materialize_legacy_step
from services.scenario_step_contract import (
    extract_data_var_for_strategy,
    normalize_extract_step,
    normalize_fb_tap_comment_step,
    normalize_save_extraction_step,
)

log = logging.getLogger(__name__)

_SERIAL_RE = re.compile(r"^[\w.:_-]{1,128}$")


def _finalize_step_results(
    *,
    success: bool,
    step_results: list,
    persisted_step_results: list,
) -> list[dict[str, Any]]:
    workflow_results = [s for s in step_results if isinstance(s, dict)]
    if success or workflow_results:
        return workflow_results
    return [s for s in persisted_step_results if isinstance(s, dict)]


def _finalize_error_message(
    *,
    failed_steps: list[dict[str, Any]],
    workflow_failed_message: str | None,
) -> str | None:
    if failed_steps:
        message = failed_steps[-1].get("message")
        if message:
            return str(message)
    return workflow_failed_message


def _finalize_is_cancelled(
    *,
    failed_steps: list[dict[str, Any]],
    workflow_failed_message: str | None,
) -> bool:
    texts: list[str] = []
    if workflow_failed_message:
        texts.append(str(workflow_failed_message))
    for step in failed_steps:
        if isinstance(step, dict):
            texts.extend(
                str(step.get(key) or "")
                for key in ("message", "failed_message", "reason_code")
            )
    return any("cancelled" in text.lower() or "canceled" in text.lower() for text in texts)


def _ignored_step_warnings_from_results(
    step_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for entry in step_results:
        if not isinstance(entry, dict) or not entry.get("ignored_failure"):
            continue
        warnings.append(
            {
                "step_index": entry.get("index"),
                "step_type": entry.get("type") or "unknown",
                "message": (
                    entry.get("ignored_message")
                    or entry.get("message")
                    or "step warning"
                ),
            }
        )
    return warnings


def _prepare_activity_step(step: dict[str, Any]) -> dict[str, Any]:
    """Epic 04 DSL → legacy executor shape before Temporal step activities run."""
    from services.execution.retry_policy import step_for_single_attempt

    prepared = materialize_legacy_step(dict(step))
    if prepared.get("type") == "extract":
        prepared = normalize_extract_step(prepared)
    elif prepared.get("type") in {"fb_tap_comment_button", "tap_fb_comment_button"}:
        prepared = normalize_fb_tap_comment_step(prepared)
    elif prepared.get("type") == "save_extraction":
        prepared = normalize_save_extraction_step(prepared)
    # Workflow-level durable retry (DF-T-04-011) owns the attempt loop in Temporal.
    return step_for_single_attempt(prepared)


def _copy_runtime_context(raw: dict[str, Any] | None) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        ctx[key] = list(value) if isinstance(value, list) else value
    return ctx


def _merge_runtime_context(
    base: dict[str, Any],
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    if not update:
        return base
    merged = dict(base)
    for key, value in update.items():
        merged[key] = list(value) if isinstance(value, list) else value
    return merged


def _build_activity_mini_scenario(step: dict[str, Any], inp: Any) -> dict[str, Any]:
    """Build 1-step mini-scenario with Epic 04 capture defaults."""
    mini_scenario: dict[str, Any] = {"steps": [step]}
    exec_id = getattr(inp, "execution_id", None) or getattr(inp, "run_id", None)
    if exec_id:
        mini_scenario["execution_id"] = exec_id
        mini_scenario["_execution_id"] = exec_id
        mini_scenario["_run_hash_scope"] = exec_id
        mini_scenario.setdefault("capture_steps", True)
    # Do not copy raw workflow campaign_id into mini-scenario: extract/save paths
    # resolve FK-safe campaign_id via resolve_persist_campaign_id. Stale IDs from
    # deleted campaigns must not leak into nested run_scenario/extract context.
    campaign_vars = getattr(inp, "campaign_vars", None)
    if campaign_vars:
        mini_scenario["_campaign_vars"] = dict(campaign_vars)
    scenario_config = getattr(inp, "scenario_config", None) or {}
    for key in (
        "visual_anchor",
        "implicit_wait",
        "capture_steps",
        "capture_throttle",
        "capture_mode",
        "settle_timeout_ms",
        "preview_collection",
        "recovery_policy",
    ):
        if key in scenario_config:
            mini_scenario[key] = scenario_config[key]
    registry = getattr(inp, "scenario_registry", None)
    if registry:
        mini_scenario["_scenario_registry"] = registry
    return mini_scenario


_STEP_EVENT_CONTEXT_MISSING = object()
_U2_BATCH_ACTION_ERROR_RE = re.compile(r"action\[(\d+)\]")


class _ExecutionFlagProbe:
    """Throttle Redis pause/cancel probes while still honoring local flags immediately."""

    def __init__(self, execution_id: str | None, *, ttl_s: float = 0.25) -> None:
        self.execution_id = execution_id
        self.ttl_s = max(0.0, float(ttl_s))
        self._cancel_checked_at = 0.0
        self._cancel_value = False
        self._pause_checked_at = 0.0
        self._pause_value = False

    async def cancelled(self, *, force: bool = False) -> bool:
        if not self.execution_id:
            return False
        from services.execution_pause_flags import (
            is_execution_cancelled_async,
            is_execution_cancelled_local,
        )

        if is_execution_cancelled_local(self.execution_id):
            self._cancel_value = True
            self._cancel_checked_at = time.monotonic()
            return True
        now = time.monotonic()
        if not force and self._cancel_checked_at and now - self._cancel_checked_at <= self.ttl_s:
            return self._cancel_value
        self._cancel_value = bool(await is_execution_cancelled_async(self.execution_id))
        self._cancel_checked_at = now
        return self._cancel_value

    async def paused(self, *, force: bool = False) -> bool:
        if not self.execution_id:
            return False
        from services.execution_pause_flags import (
            is_execution_paused_async,
            is_execution_paused_local,
        )

        if is_execution_paused_local(self.execution_id):
            self._pause_value = True
            self._pause_checked_at = time.monotonic()
            return True
        now = time.monotonic()
        if not force and self._pause_checked_at and now - self._pause_checked_at <= self.ttl_s:
            return self._pause_value
        self._pause_value = bool(await is_execution_paused_async(self.execution_id))
        self._pause_checked_at = now
        return self._pause_value


async def _resolve_step_event_context(
    inp: DeviceActionInput | DeviceActionBatchInput,
) -> tuple[Any, Any] | None:
    execution_id = getattr(inp, "execution_id", None)
    if not execution_id:
        return None
    from db.database import activity_session
    from services.execution.event_publisher import resolve_execution_event_context

    async with activity_session() as db:
        _, org_id, camp_id = await resolve_execution_event_context(db, execution_id)
    if not org_id:
        return None
    return org_id, (getattr(inp, "campaign_id", None) or camp_id)


async def _cached_step_event_context(
    inp: DeviceActionInput | DeviceActionBatchInput,
    cache: dict[str, Any],
) -> tuple[Any, Any] | None:
    if "value" not in cache:
        cache["value"] = await _resolve_step_event_context(inp)
    return cache["value"]


def _screen_size(device: Any) -> tuple[int, int]:
    w = int(getattr(device, "screen_width", 0) or 1080)
    h = int(getattr(device, "screen_height", 0) or 1920)
    return w, h


def _tap_position_action(step: dict[str, Any], device: Any) -> dict[str, Any]:
    pos = str(step.get("pos") or "middle_center")
    if pos == "top_center":
        rx, ry = 0.5, 0.1
    elif pos == "search_bar":
        rx, ry = 0.5, 0.18
    elif pos == "bottom_center":
        rx, ry = 0.5, 0.9
    else:
        rx, ry = 0.5, 0.5
    w, h = _screen_size(device)
    return {
        "op": "click",
        "x": max(0, min(w - 1, int(rx * w))),
        "y": max(0, min(h - 1, int(ry * h))),
    }


def _swipe_ratio_action(step: dict[str, Any], device: Any) -> dict[str, Any]:
    try:
        rx1 = float(step.get("x1", 0.5))
        ry1 = float(step.get("y1", 0.5))
        rx2 = float(step.get("x2", 0.5))
        ry2 = float(step.get("y2", 0.5))
        duration_ms = int(step.get("duration_ms", 300) or 300)
    except Exception:
        rx1, ry1, rx2, ry2, duration_ms = 0.5, 0.5, 0.5, 0.5, 300
    w, h = _screen_size(device)
    return {
        "op": "swipe",
        "fx": max(0, min(w - 1, int(rx1 * w))),
        "fy": max(0, min(h - 1, int(ry1 * h))),
        "tx": max(0, min(w - 1, int(rx2 * w))),
        "ty": max(0, min(h - 1, int(ry2 * h))),
        "duration": max(0.0, duration_ms / 1000.0),
    }


def _primitive_touch_action(step: dict[str, Any], device: Any) -> dict[str, Any] | None:
    if step.get("ignore_error"):
        return None
    step_type = str(step.get("type") or "")
    if step_type == "tap_position":
        return _tap_position_action(step, device)
    if step_type == "swipe_ratio":
        return _swipe_ratio_action(step, device)
    return None


def _primitive_touch_timeout(actions: list[dict[str, Any]]) -> float:
    total = 0.0
    for action in actions:
        if action.get("op") == "swipe":
            total += max(1.5, float(action.get("duration", 0.0) or 0.0) + 0.8)
        else:
            total += 1.5
    return min(30.0, max(1.5, total))


def _u2_batch_failure_action_index(exc: BaseException, action_count: int) -> int:
    match = _U2_BATCH_ACTION_ERROR_RE.search(str(exc))
    if not match:
        return 0
    try:
        idx = int(match.group(1))
    except Exception:
        return 0
    return max(0, min(idx, max(0, action_count - 1)))


def _u2_batch_failure_results(exc: BaseException) -> list[dict[str, Any]]:
    results = getattr(exc, "results", None)
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _primitive_touch_batch_size(inp: DeviceActionBatchInput) -> int:
    scenario_config = getattr(inp, "scenario_config", None) or {}
    try:
        size = int(scenario_config.get("primitive_touch_batch_size", 10) or 10)
    except Exception:
        size = 10
    return max(1, min(size, 10))


def _collect_primitive_touch_batch(
    *,
    steps: list[dict[str, Any]],
    step_indices: list[int],
    start: int,
    device: Any,
    max_actions: int = 1,
) -> tuple[list[dict[str, Any]], list[int], list[dict[str, Any]], float]:
    if not callable(getattr(device, "_batch_enabled", None)) or not device._batch_enabled():
        return [], [], [], 0.0

    prepared_steps: list[dict[str, Any]] = []
    original_indices: list[int] = []
    actions: list[dict[str, Any]] = []
    for pos in range(start, len(steps)):
        if len(actions) >= max(1, max_actions):
            break
        prepared = _prepare_activity_step(steps[pos])
        action = _primitive_touch_action(prepared, device)
        if action is None:
            break
        prepared_steps.append(prepared)
        original_indices.append(step_indices[pos])
        actions.append(action)
    return prepared_steps, original_indices, actions, _primitive_touch_timeout(actions)

# Global device registry reference — set by worker at startup (before any activity runs).
_device_registry = None
_temporal_config = None


def set_device_registry(registry) -> None:
    """Called by worker startup to inject DeviceManager reference."""
    global _device_registry
    _device_registry = registry


def set_temporal_config(cfg) -> None:
    """Called by worker startup to inject TemporalConfig for finalize_campaign."""
    global _temporal_config
    _temporal_config = cfg


def _safe_activity_heartbeat(detail: str = "") -> None:
    """Best-effort Temporal heartbeat; never raises."""
    with contextlib.suppress(Exception):
        activity.heartbeat(detail or "running")


def _is_cancellation_exc(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.CancelledError):
        return True
    with contextlib.suppress(ImportError):
        from temporalio.exceptions import CancelledError as _TemporalCancelledError
        return isinstance(exc, _TemporalCancelledError)
    return False


async def _to_thread_with_heartbeat(
    fn: Callable,
    *args: Any,
    heartbeat_interval: float = 5.0,
    cooperative_cancel_event: threading.Event | None = None,
    cancel_grace_s: float = 5.0,
    execution_id: str | None = None,
    stop_on_pause: bool = False,
    **kwargs: Any,
) -> Any:
    """Run a sync blocking function in the thread pool while sending Temporal heartbeats.

    Without this, an activity with heartbeat_timeout=30s that blocks for >30s in a
    thread (waiting for UI elements, scrolling, etc.) will be cancelled by Temporal
    with CancelledError because no heartbeat arrives within the timeout window.

    heartbeat_interval should be well under heartbeat_timeout (default 5s vs 60s batch).

    When *execution_id* is set, cooperative cancel also polls the runtime cancel flag
    (set by execution_control on cancel) so activities can finish gracefully without
    Temporal force-cancelling the asyncio task.
    """
    thread_task: asyncio.Task[Any] | None = None
    # Always track cancel signals — even when the worker fn has no cancel_event arg,
    # Temporal timeout/cancel must release the activity slot (after cancel_grace_s).
    cancel_event = cooperative_cancel_event or threading.Event()
    fn_name = getattr(fn, "__name__", repr(fn))
    thread_ctx = {
        **activity_log_context(),
        "execution_id": execution_id,
        "thread_fn": fn_name,
    }
    trace_log.info("temporal_thread_start", **thread_ctx)

    async def _maybe_signal_cancel() -> bool:
        if cancel_event.is_set():
            return True
        with contextlib.suppress(Exception):
            if activity.is_cancelled():
                cancel_event.set()
                trace_log.warning(
                    "temporal_thread_cancel",
                    **thread_ctx,
                    reason="temporal_activity_cancelled",
                )
                return True
        if execution_id:
            with contextlib.suppress(Exception):
                from services.execution_pause_flags import is_execution_cancelled_async
                if await is_execution_cancelled_async(execution_id):
                    cancel_event.set()
                    trace_log.warning(
                        "temporal_thread_cancel",
                        **thread_ctx,
                        reason="execution_cancel_flag",
                    )
                    return True
            if stop_on_pause:
                with contextlib.suppress(Exception):
                    from services.execution_pause_flags import is_execution_paused_async
                    if await is_execution_paused_async(execution_id):
                        cancel_event.set()
                        trace_log.warning(
                            "temporal_thread_cancel",
                            **thread_ctx,
                            reason="execution_pause_flag",
                        )
                        return True
        return False

    async def _heartbeat_loop() -> None:
        n = 0
        while True:
            await asyncio.sleep(heartbeat_interval)
            _safe_activity_heartbeat(f"running:{n}")
            await _maybe_signal_cancel()
            n += 1

    async def _cancel_watcher() -> None:
        while True:
            await asyncio.sleep(0.25)
            if await _maybe_signal_cancel():
                return

    async def _wait_for_thread_after_cancel() -> Any:
        nonlocal thread_task
        cancel_event.set()
        if thread_task is None:
            raise asyncio.CancelledError()
        try:
            return await asyncio.wait_for(asyncio.shield(thread_task), timeout=cancel_grace_s)
        except asyncio.TimeoutError:
            trace_log.warning(
                "temporal_thread_slot_released",
                **thread_ctx,
                reason="grace_timeout",
                cancel_grace_s=cancel_grace_s,
            )
            raise asyncio.CancelledError() from None

    # Emit one heartbeat immediately so short timeout windows don't expire
    # before the first sleep tick under high worker load.
    _safe_activity_heartbeat("running:start")
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    cancel_watch_task = asyncio.create_task(_cancel_watcher())
    thread_task = asyncio.create_task(asyncio.to_thread(functools.partial(fn, *args, **kwargs)))
    try:
        while not thread_task.done():
            done, _pending = await asyncio.wait(
                {thread_task, cancel_watch_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if thread_task in done:
                trace_log.info("temporal_thread_end", **thread_ctx, ok=True)
                return thread_task.result()
            # Cancel watcher fired — give the worker thread time to stop cooperatively.
            return await _wait_for_thread_after_cancel()
        trace_log.info("temporal_thread_end", **thread_ctx, ok=True)
        return thread_task.result()
    except BaseException as exc:
        if _is_cancellation_exc(exc):
            with contextlib.suppress(Exception, asyncio.CancelledError, asyncio.TimeoutError):
                return await _wait_for_thread_after_cancel()
        raise
    finally:
        heartbeat_task.cancel()
        cancel_watch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        with contextlib.suppress(asyncio.CancelledError):
            await cancel_watch_task


def _validate_serial(serial: str) -> None:
    """Validate device serial to prevent injection attacks."""
    if not serial or not _SERIAL_RE.match(serial):
        raise ValueError(f"Invalid device serial: {serial!r}")


def _get_device(serial: str):
    """Get DeviceClient from the global device registry."""
    _validate_serial(serial)
    registry = _device_registry
    if registry is None:
        raise RuntimeError("Device registry not initialized — worker not started")
    device = registry.get_device(serial)
    if device is None:
        raise RuntimeError(f"Device {serial!r} not found in registry")
    return device


async def _emit_step_events_for_activity(
    inp: DeviceActionInput | DeviceActionBatchInput,
    *,
    step: dict[str, Any],
    step_index: int,
    step_result: dict[str, Any] | None = None,
    phase: str,
    event_context: tuple[Any, Any] | None | object = _STEP_EVENT_CONTEXT_MISSING,
    event_context_cache: dict[str, Any] | None = None,
) -> None:
    execution_id = getattr(inp, "execution_id", None)
    if not execution_id:
        return
    from db.database import activity_session
    from services.execution.activity_events import emit_step_finished, emit_step_started
    from services.execution.event_publisher import process_outbox_batch, resolve_execution_event_context

    from tenancy.context import tenant_context

    if event_context is _STEP_EVENT_CONTEXT_MISSING and event_context_cache is not None:
        event_context = await _cached_step_event_context(inp, event_context_cache)
    if event_context is None:
        return

    async with activity_session() as db:
        if event_context is _STEP_EVENT_CONTEXT_MISSING:
            _, org_id, camp_id = await resolve_execution_event_context(db, execution_id)
            if not org_id:
                return
            campaign_id = getattr(inp, "campaign_id", None) or camp_id
        else:
            org_id, campaign_id = event_context
        with tenant_context(org_id):
            if phase == "started":
                await emit_step_started(
                    db,
                    execution_id=execution_id,
                    org_id=org_id,
                    campaign_id=campaign_id,
                    step=step,
                    step_index=step_index,
                    depth=getattr(inp, "depth", 0),
                )
            elif phase == "finished" and step_result is not None:
                await emit_step_finished(
                    db,
                    execution_id=execution_id,
                    org_id=org_id,
                    campaign_id=campaign_id,
                    step=step,
                    step_index=step_index,
                    step_result=step_result,
                    depth=getattr(inp, "depth", 0),
                )
            await process_outbox_batch(db)
            await db.commit()


class DeviceActivities:
    """
    Temporal activity methods for device interaction.

    execute_device_action delegates to the original run_scenario_task()
    which has the full, battle-tested execution pipeline:
    - pre_hash → auto_dismiss_popup → _execute_tap(retries=2) → _wait_ui_change
    - Smart waits, fallback logic, container class skip, wrong element detection

    Credential cache: account passwords are fetched once per account_id and
    cached for the lifetime of this Worker instance. activity_session() creates
    a new async engine per call (NullPool), so caching avoids repeated
    engine-create/dispose on every step of a multi-step campaign.
    """

    def __init__(self) -> None:
        # account_id -> decrypted password; populated lazily, never evicted
        # (passwords don't change mid-campaign; Worker restarts clear the cache).
        self._cred_cache: dict[str, str] = {}
        # Prevents duplicate DB fetches when two coroutines miss the cache
        # simultaneously for the same account_id.
        self._cred_lock: asyncio.Lock = asyncio.Lock()

    async def _resolve_password(
        self,
        account_id: str,
        *,
        execution_id: str | None = None,
    ) -> str | None:
        """Fetch and cache the decrypted password for account_id.

        The lock prevents the check-then-act race: without it, two coroutines
        could both miss the cache and issue duplicate DB queries for the same
        account. The fast path (cache hit) does not acquire the lock.
        """
        if account_id in self._cred_cache:
            return self._cred_cache[account_id]
        async with self._cred_lock:
            # Re-check after acquiring lock — another coroutine may have
            # populated the cache while we waited.
            if account_id in self._cred_cache:
                return self._cred_cache[account_id]
            from db.database import activity_session
            from db.crud.account import get_account, lookup_account_org_id
            from common.crypto import decrypt_password
            from services.execution.event_publisher import resolve_execution_org_id
            from tenancy.context import tenant_context

            org_id = ""
            async with activity_session() as acct_db:
                if execution_id:
                    org_id = await resolve_execution_org_id(acct_db, execution_id)
                if not org_id:
                    org_id = (await lookup_account_org_id(acct_db, account_id)) or ""
                with tenant_context(org_id or None):
                    account = await get_account(acct_db, account_id)
                if account is None:
                    return None
                pwd = decrypt_password(account.password_encrypted)
            self._cred_cache[account_id] = pwd
            return pwd

    @activity.defn
    async def execute_device_action(self, inp: DeviceActionInput) -> StepResult:
        """
        Execute a single device action step using the original scenario executor.

        Wraps run_scenario_task() with a 1-step scenario so we get the full
        pipeline: popup dismiss, smart waits, selector fallback, UI change
        detection — exactly as described in flow.md.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        step = _prepare_activity_step(dict(inp.step))
        step_type = step.get("type", "")
        idx = inp.step_index

        activity.heartbeat(f"step:{idx}:{step_type}")

        try:
            # Import here to avoid circular imports at module level
            from tasks.scenario_task import run_scenario_task
            from common.variable_resolver import VariableContext

            # Build a 1-step scenario and run it through the ORIGINAL executor.
            # Merge scenario-level config (visual_anchor, implicit_wait, etc.)
            # so each mini-scenario inherits the parent's settings.
            mini_scenario = _build_activity_mini_scenario(step, inp)

            # Create VariableContext with all variable layers
            resolved_campaign_vars = dict(inp.campaign_vars)

            # SECURITY: Credentials resolved at activity time — never stored in Temporal
            # event history. __ACCOUNT_ID__ is a safe reference; password is fetched+decrypted
            # inside _resolve_password() (activity-local) and passed via scenario_vars,
            # NOT campaign_vars, to prevent leaking into serialized workflow state.
            credential_vars: dict[str, Any] = {}
            acct_id = resolved_campaign_vars.get("__ACCOUNT_ID__") or inp.variables.get("__ACCOUNT_ID__")
            if acct_id:
                pwd = await self._resolve_password(
                    acct_id, execution_id=inp.execution_id,
                )
                if pwd is None:
                    return StepResult(
                        index=idx, step_type=step_type, ok=False,
                        message=(
                            f"Account {acct_id!r} not found — cannot resolve credentials. "
                            "Check that the account still exists in the database."
                        ),
                    )
                credential_vars["__ACCOUNT_PASSWORD__"] = pwd

            var_ctx = VariableContext(
                # Merge credentials into scenario_vars (activity-scoped) so the
                # password is available for variable resolution but never enters
                # campaign_vars, which could be serialized or logged.
                scenario_vars={**inp.variables, **credential_vars},
                campaign_vars=resolved_campaign_vars,
                device_serial=inp.device_serial,
                device_model=getattr(device, "model", ""),
            )
            cancel_event = threading.Event()

            _safe_activity_heartbeat(f"step:{idx}:emit_started")
            await _emit_step_events_for_activity(
                inp, step=step, step_index=idx, phase="started",
            )

            activity_step_started = time.monotonic()
            result = await _to_thread_with_heartbeat(
                run_scenario_task,
                device,
                mini_scenario,
                context=_copy_runtime_context(getattr(inp, "context", None)),
                _var_ctx=var_ctx,
                cancel_event=cancel_event,
                cooperative_cancel_event=cancel_event,
                execution_id=inp.execution_id,
            )
            activity_step_duration_ms = round(
                (time.monotonic() - activity_step_started) * 1000.0,
                1,
            )

            # Extract the single step result
            step_results = result.get("step_results", [])
            if step_results:
                sr = dict(step_results[0])
                sr.setdefault("duration_ms", activity_step_duration_ms)
                sr.setdefault("activity_duration_ms", activity_step_duration_ms)

                await _emit_step_events_for_activity(
                    inp, step=step, step_index=idx, step_result=sr, phase="finished",
                )

                # Self-healing hook: if selector healed during image-match,
                # include the healed selector in details for the caller to persist.
                details = {
                    k: v for k, v in sr.items()
                    if k not in ("index", "type", "ok", "message")
                }

                return StepResult(
                    index=idx,
                    step_type=step_type,
                    ok=sr.get("ok", False),
                    message=sr.get("message") or "",
                    details=details,
                    context=_copy_runtime_context(result.get("context")),
                )

            # No step results — check overall success
            return StepResult(
                index=idx,
                step_type=step_type,
                ok=result.get("success", False),
                message=result.get("failed_message") or "",
                details={
                    "duration_ms": activity_step_duration_ms,
                    "activity_duration_ms": activity_step_duration_ms,
                },
            )

        except BaseException as exc:
            if _is_cancellation_exc(exc):
                raise
            if not isinstance(exc, Exception):
                raise  # re-raise other BaseException (KeyboardInterrupt, SystemExit, etc.)
            log.error(
                "[%s] activity error step#%d (%s): %s",
                inp.device_serial, idx, step_type, exc,
            )
            return StepResult(
                index=idx, step_type=step_type, ok=False,
                message=f"Activity error: {exc}",
            )

    @activity.defn
    async def execute_device_action_batch(
        self, inp: DeviceActionBatchInput,
    ) -> DeviceActionBatchResult:
        """Run N consecutive leaf steps as one activity call.

        History cost: 3 events regardless of batch size (vs 3N for individual calls).
        Steps are executed sequentially; stops on the first failure unless
        the step has ignore_error=True.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        _safe_activity_heartbeat(f"batch:0/{len(inp.steps)}")

        from tasks.scenario_task import run_scenario_task
        from common.variable_resolver import VariableContext

        results: list[dict[str, Any]] = []
        first_failure_index = -1

        # Resolve credentials once for the whole batch.
        credential_vars: dict[str, Any] = {}
        acct_id = inp.campaign_vars.get("__ACCOUNT_ID__") or inp.variables.get("__ACCOUNT_ID__")
        if acct_id:
            pwd = await self._resolve_password(
                acct_id, execution_id=inp.execution_id,
            )
            if pwd is None:
                return DeviceActionBatchResult(
                    results=[{
                        "index": inp.step_indices[0] if inp.step_indices else 0,
                        "type": "batch",
                        "ok": False,
                        "message": f"Account {acct_id!r} not found",
                    }],
                    first_failure_index=0,
                )
            credential_vars["__ACCOUNT_PASSWORD__"] = pwd

        var_ctx = VariableContext(
            scenario_vars={**inp.variables, **credential_vars},
            campaign_vars=inp.campaign_vars,
            device_serial=inp.device_serial,
            device_model=getattr(device, "model", ""),
        )
        cancel_event = threading.Event()
        batch_context = _copy_runtime_context(getattr(inp, "context", None))
        flag_probe = _ExecutionFlagProbe(inp.execution_id)
        event_context_cache: dict[str, Any] = {}
        touch_batch_size = _primitive_touch_batch_size(inp)

        batch_pos = 0
        while batch_pos < len(inp.steps):
            _safe_activity_heartbeat(f"batch:{batch_pos}/{len(inp.steps)}")
            if activity.is_cancelled():
                return DeviceActionBatchResult(
                    results=results,
                    first_failure_index=-1,
                    cancelled_mid_batch=True,
                    context=batch_context,
                )
            if await flag_probe.cancelled():
                return DeviceActionBatchResult(
                    results=results,
                    first_failure_index=-1,
                    cancelled_mid_batch=True,
                    context=batch_context,
                )
            with contextlib.suppress(Exception):
                device.ensure_u2_healthy(ping_timeout=2.0)
            if await flag_probe.paused():
                return DeviceActionBatchResult(
                    results=results,
                    first_failure_index=-1,
                    paused_mid_batch=True,
                    context=batch_context,
                )

            touch_steps, touch_indices, touch_actions, touch_timeout = _collect_primitive_touch_batch(
                steps=inp.steps,
                step_indices=inp.step_indices,
                start=batch_pos,
                device=device,
                max_actions=touch_batch_size,
            )
            if touch_actions:
                try:
                    u2_batch_started = time.monotonic()
                    batch_u2_results = await _to_thread_with_heartbeat(
                        device.u2_batch,
                        touch_actions,
                        timeout=touch_timeout,
                        cancel_event=cancel_event,
                        cooperative_cancel_event=cancel_event,
                        execution_id=inp.execution_id,
                        stop_on_pause=True,
                    )
                    u2_batch_duration_ms = round(
                        (time.monotonic() - u2_batch_started) * 1000.0,
                        1,
                    )
                    u2_batch_action_duration_ms = round(
                        u2_batch_duration_ms / max(1, len(touch_actions)),
                        1,
                    )

                    consumed = 0
                    for rel, (touch_step, touch_idx) in enumerate(zip(touch_steps, touch_indices)):
                        action_result = (
                            batch_u2_results[rel]
                            if isinstance(batch_u2_results, list) and rel < len(batch_u2_results)
                            else {"ok": False, "error": "u2_batch returned no result"}
                        )
                        ok = bool(isinstance(action_result, dict) and action_result.get("ok"))
                        message = "" if ok else str(
                            action_result.get("error")
                            if isinstance(action_result, dict)
                            else action_result
                        )
                        sr = {
                            "index": touch_idx,
                            "type": touch_step.get("type", ""),
                            "ok": ok,
                            "message": message,
                            "duration_ms": u2_batch_action_duration_ms,
                            "u2_batch_duration_ms": u2_batch_duration_ms,
                            "u2_batch_action_duration_ms": u2_batch_action_duration_ms,
                        }
                        entry = {
                            "index": touch_idx,
                            "type": touch_step.get("type", ""),
                            "ok": ok,
                            "message": message,
                            "details": {
                                "duration_ms": u2_batch_action_duration_ms,
                                "u2_batch_duration_ms": u2_batch_duration_ms,
                                "u2_batch_action_duration_ms": u2_batch_action_duration_ms,
                            },
                        }
                        _safe_activity_heartbeat(f"batch:{batch_pos + rel}:emit_started")
                        await _emit_step_events_for_activity(
                            inp,
                            step=touch_step,
                            step_index=touch_idx,
                            phase="started",
                            event_context_cache=event_context_cache,
                        )
                        _safe_activity_heartbeat(f"batch:{batch_pos + rel}:emit_finished")
                        await _emit_step_events_for_activity(
                            inp,
                            step=touch_step,
                            step_index=touch_idx,
                            step_result=sr,
                            phase="finished",
                            event_context_cache=event_context_cache,
                        )
                        results.append(entry)
                        consumed += 1
                        if not ok:
                            first_failure_index = batch_pos + rel
                            break

                    if first_failure_index != -1:
                        break
                    if cancel_event.is_set() and await flag_probe.paused(force=True):
                        return DeviceActionBatchResult(
                            results=results,
                            first_failure_index=-1,
                            paused_mid_batch=True,
                            context=batch_context,
                        )
                    if cancel_event.is_set() or await flag_probe.cancelled(force=cancel_event.is_set()):
                        return DeviceActionBatchResult(
                            results=results,
                            first_failure_index=-1,
                            cancelled_mid_batch=True,
                            context=batch_context,
                        )
                    if await flag_probe.paused():
                        return DeviceActionBatchResult(
                            results=results,
                            first_failure_index=-1,
                            paused_mid_batch=True,
                            context=batch_context,
                        )

                    batch_pos += consumed
                    continue
                except BaseException as exc:
                    step = touch_steps[0]
                    step_idx = touch_indices[0]
                    step_type = step.get("type", "")
                    partial_results = _u2_batch_failure_results(exc)
                    if cancel_event.is_set():
                        for rel, action_result in enumerate(partial_results):
                            if rel >= len(touch_steps):
                                break
                            if not bool(action_result.get("ok")):
                                break
                            touch_step = touch_steps[rel]
                            touch_idx = touch_indices[rel]
                            sr = {
                                "index": touch_idx,
                                "type": touch_step.get("type", ""),
                                "ok": True,
                                "message": "",
                            }
                            entry = {
                                "index": touch_idx,
                                "type": touch_step.get("type", ""),
                                "ok": True,
                                "message": "",
                                "details": {},
                            }
                            _safe_activity_heartbeat(f"batch:{batch_pos + rel}:emit_started")
                            await _emit_step_events_for_activity(
                                inp,
                                step=touch_step,
                                step_index=touch_idx,
                                phase="started",
                                event_context_cache=event_context_cache,
                            )
                            _safe_activity_heartbeat(f"batch:{batch_pos + rel}:emit_finished")
                            await _emit_step_events_for_activity(
                                inp,
                                step=touch_step,
                                step_index=touch_idx,
                                step_result=sr,
                                phase="finished",
                                event_context_cache=event_context_cache,
                            )
                            results.append(entry)
                        if await flag_probe.paused(force=True):
                            return DeviceActionBatchResult(
                                results=results,
                                first_failure_index=-1,
                                paused_mid_batch=True,
                                context=batch_context,
                            )
                        if await flag_probe.cancelled(force=True):
                            return DeviceActionBatchResult(
                                results=results,
                                first_failure_index=-1,
                                cancelled_mid_batch=True,
                                context=batch_context,
                            )
                        return DeviceActionBatchResult(
                            results=results,
                            first_failure_index=-1,
                            cancelled_mid_batch=True,
                            context=batch_context,
                        )
                    if _is_cancellation_exc(exc):
                        log.info(
                            "[%s] batch activity cooperatively cancelled at step#%d (%s) pos=%d/%d",
                            inp.device_serial, step_idx, step_type, batch_pos, len(inp.steps),
                        )
                        return DeviceActionBatchResult(
                            results=results,
                            first_failure_index=-1,
                            cancelled_mid_batch=True,
                            context=batch_context,
                        )
                    if not isinstance(exc, Exception):
                        raise
                    stopped_at = getattr(exc, "stopped_at", None)
                    failure_rel = _u2_batch_failure_action_index(exc, len(touch_steps))
                    if stopped_at is not None:
                        with contextlib.suppress(Exception):
                            failure_rel = int(stopped_at)
                    failure_rel = max(0, min(failure_rel, len(touch_steps) - 1))
                    log.error(
                        "[%s] batch touch step#%d (%s): %s",
                        inp.device_serial,
                        touch_indices[failure_rel],
                        touch_steps[failure_rel].get("type", ""),
                        exc,
                    )
                    for rel, (touch_step, touch_idx) in enumerate(
                        zip(touch_steps[: failure_rel + 1], touch_indices[: failure_rel + 1])
                    ):
                        action_result = (
                            partial_results[rel]
                            if rel < len(partial_results)
                            else None
                        )
                        ok = (
                            bool(action_result.get("ok"))
                            if isinstance(action_result, dict)
                            else rel < failure_rel
                        )
                        message = ""
                        if not ok:
                            message = str(
                                action_result.get("error")
                                if isinstance(action_result, dict) and action_result.get("error")
                                else exc
                            )
                        sr = {
                            "index": touch_idx,
                            "type": touch_step.get("type", ""),
                            "ok": ok,
                            "message": message,
                        }
                        entry = {
                            "index": touch_idx,
                            "type": touch_step.get("type", ""),
                            "ok": ok,
                            "message": message,
                            "details": {},
                        }
                        _safe_activity_heartbeat(f"batch:{batch_pos + rel}:emit_started")
                        await _emit_step_events_for_activity(
                            inp,
                            step=touch_step,
                            step_index=touch_idx,
                            phase="started",
                            event_context_cache=event_context_cache,
                        )
                        _safe_activity_heartbeat(f"batch:{batch_pos + rel}:emit_finished")
                        await _emit_step_events_for_activity(
                            inp,
                            step=touch_step,
                            step_index=touch_idx,
                            step_result=sr,
                            phase="finished",
                            event_context_cache=event_context_cache,
                        )
                        results.append(entry)
                    first_failure_index = batch_pos + failure_rel
                    break

            step = inp.steps[batch_pos]
            step_idx = inp.step_indices[batch_pos]
            step_type = step.get("type", "")
            step = _prepare_activity_step(step)
            step_type = step.get("type", "")
            mini_scenario = _build_activity_mini_scenario(step, inp)

            try:
                _safe_activity_heartbeat(f"batch:{batch_pos}:emit_started")
                await _emit_step_events_for_activity(
                    inp,
                    step=step,
                    step_index=step_idx,
                    phase="started",
                    event_context_cache=event_context_cache,
                )
                activity_step_started = time.monotonic()
                result = await _to_thread_with_heartbeat(
                    run_scenario_task,
                    device,
                    mini_scenario,
                    context=batch_context,
                    _var_ctx=var_ctx,
                    cancel_event=cancel_event,
                    cooperative_cancel_event=cancel_event,
                    execution_id=inp.execution_id,
                )
                activity_step_duration_ms = round(
                    (time.monotonic() - activity_step_started) * 1000.0,
                    1,
                )
                batch_context = _merge_runtime_context(
                    batch_context,
                    result.get("context") if isinstance(result.get("context"), dict) else None,
                )
                if cancel_event.is_set() or await flag_probe.cancelled():
                    log.info(
                        "[%s] batch cooperatively cancelled at step#%d (%s) pos=%d/%d",
                        inp.device_serial, step_idx, step_type, batch_pos, len(inp.steps),
                    )
                    step_results = result.get("step_results", [])
                    sr = dict(step_results[0]) if step_results else {
                        "index": step_idx,
                        "type": step_type,
                        "ok": False,
                        "message": "cancelled by user",
                    }
                    sr.setdefault("index", step_idx)
                    sr.setdefault("type", step_type)
                    sr.setdefault("ok", False)
                    sr.setdefault("duration_ms", activity_step_duration_ms)
                    sr.setdefault("activity_duration_ms", activity_step_duration_ms)
                    entry = {
                        "index": step_idx,
                        "type": step_type,
                        "ok": sr.get("ok", False),
                        "message": sr.get("message") or "",
                        "details": {
                            k: v for k, v in sr.items()
                            if k not in ("index", "type", "ok", "message")
                        },
                    }
                    results.append(entry)
                    _safe_activity_heartbeat(f"batch:{batch_pos}:emit_finished")
                    await _emit_step_events_for_activity(
                        inp,
                        step=step,
                        step_index=step_idx,
                        step_result=sr,
                        phase="finished",
                        event_context_cache=event_context_cache,
                    )
                    return DeviceActionBatchResult(
                        results=results,
                        first_failure_index=-1,
                        cancelled_mid_batch=True,
                        context=batch_context,
                    )
                step_results = result.get("step_results", [])
                if step_results:
                    sr = dict(step_results[0])
                    sr.setdefault("duration_ms", activity_step_duration_ms)
                    sr.setdefault("activity_duration_ms", activity_step_duration_ms)
                    entry = {
                        "index": step_idx, "type": step_type,
                        "ok": sr.get("ok", False),
                        "message": sr.get("message") or "",
                        "details": {k: v for k, v in sr.items()
                                    if k not in ("index", "type", "ok", "message")},
                    }
                    _safe_activity_heartbeat(f"batch:{batch_pos}:emit_finished")
                    await _emit_step_events_for_activity(
                        inp,
                        step=step,
                        step_index=step_idx,
                        step_result=sr,
                        phase="finished",
                        event_context_cache=event_context_cache,
                    )
                else:
                    entry = {
                        "index": step_idx, "type": step_type,
                        "ok": result.get("success", False),
                        "message": result.get("failed_message") or "",
                        "details": {
                            "duration_ms": activity_step_duration_ms,
                            "activity_duration_ms": activity_step_duration_ms,
                        },
                    }
            except BaseException as exc:
                if _is_cancellation_exc(exc):
                    log.info(
                        "[%s] batch activity cooperatively cancelled at step#%d (%s) pos=%d/%d",
                        inp.device_serial, step_idx, step_type, batch_pos, len(inp.steps),
                    )
                    return DeviceActionBatchResult(
                        results=results,
                        first_failure_index=-1,
                        cancelled_mid_batch=True,
                    )
                if not isinstance(exc, Exception):
                    raise
                log.error("[%s] batch step#%d (%s): %s", inp.device_serial, step_idx, step_type, exc)
                entry = {"index": step_idx, "type": step_type, "ok": False, "message": str(exc)}

            results.append(entry)
            if not entry["ok"] and not step.get("ignore_error"):
                first_failure_index = batch_pos
                break
            batch_pos += 1

        return DeviceActionBatchResult(
            results=results,
            first_failure_index=first_failure_index,
            context=batch_context,
        )

    @activity.defn
    async def check_element_exists(self, inp: ElementCheckInput) -> ElementCheckResult:
        """
        Check if a UI element exists on the device screen.

        Uses the same _wait_for_element from scenario_task.py for consistency.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        try:
            from runtime.core.device_client import DeviceState

            if getattr(device, "u2", None) is not None and getattr(device, "state", None) == DeviceState.DEAD:
                active = int(getattr(device, "_scenario_active", 0) or 0)
                device.state = DeviceState.BUSY if active > 0 else DeviceState.READY
                trace_log.warning(
                    "check_element_state_repaired",
                    device_serial=inp.device_serial,
                    execution_id=inp.execution_id,
                    from_state=DeviceState.DEAD.value,
                    to_state=device.state.value,
                    scenario_active=active,
                )
        except Exception as exc:
            log.debug("[%s] check_element state repair skipped: %s", inp.device_serial, exc)
        activity.heartbeat(f"check_element:{inp.by}={inp.value}")
        trace_log.info(
            "check_element_start",
            device_serial=inp.device_serial,
            execution_id=inp.execution_id,
            by=inp.by,
            value=inp.value,
            timeout=inp.timeout,
            u2_ready=device.u2 is not None,
            device_state=str(getattr(getattr(device, "state", None), "value", getattr(device, "state", None))),
        )

        try:
            from tasks.scenario_task import _wait_for_element

            u2 = device.u2
            if u2 is None:
                device.ensure_u2_healthy()
                u2 = device.u2

            if u2 is None:
                trace_log.warning(
                    "check_element_end",
                    device_serial=inp.device_serial,
                    execution_id=inp.execution_id,
                    found=False,
                    message="u2 not available",
                )
                return ElementCheckResult(found=False, message="u2 not available")

            cancel_event = threading.Event()
            eid = await _to_thread_with_heartbeat(
                _wait_for_element,
                u2,
                inp.by,
                inp.value,
                timeout=inp.timeout,
                cancel_event=cancel_event,
                cooperative_cancel_event=cancel_event,
                execution_id=inp.execution_id,
            )
            found = eid is not None
            message = f"element {inp.by}={inp.value!r}: {'found' if found else 'not found'}"
            trace_log.info(
                "check_element_end",
                device_serial=inp.device_serial,
                execution_id=inp.execution_id,
                found=found,
                message=message,
            )
            return ElementCheckResult(found=found, message=message)
        except asyncio.CancelledError:
            trace_log.warning(
                "check_element_end",
                device_serial=inp.device_serial,
                execution_id=inp.execution_id,
                found=False,
                message="cancelled",
            )
            return ElementCheckResult(found=False, message="cancelled")
        except Exception as exc:
            trace_log.warning(
                "check_element_end",
                device_serial=inp.device_serial,
                execution_id=inp.execution_id,
                found=False,
                error=str(exc)[:300],
            )
            log.debug("[%s] check_element error: %s", inp.device_serial, exc)
            return ElementCheckResult(found=False, message=f"check error: {exc}")

    @activity.defn
    async def evaluate_legacy_condition(self, inp: LegacyConditionCheckInput) -> bool:
        """
        Evaluate a generic condition dict (if / loop while / break_if steps).

        Supports: element_exists, element_not_exists, posts_count_gte,
        posts_count_lt, no_new_posts. Delegates to _evaluate_condition from
        scenario_task.py so condition semantics stay in one place.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        activity.heartbeat("evaluate_legacy_condition")

        try:
            from tasks.scenario_task import _evaluate_condition

            # Reconstruct a ctx dict that _evaluate_condition expects.
            # Merge: runtime_vars under "vars" key + flat context keys (posts, etc.)
            ctx: dict[str, Any] = dict(inp.context)
            if inp.runtime_vars:
                ctx.setdefault("vars", {}).update(inp.runtime_vars)

            cancel_event = threading.Event()
            return await _to_thread_with_heartbeat(
                _evaluate_condition,
                device,
                inp.condition,
                ctx,
                cooperative_cancel_event=cancel_event,
                execution_id=inp.execution_id,
            )
        except asyncio.CancelledError:
            return False
        except Exception as exc:
            log.error("[%s] evaluate_legacy_condition error: %s", inp.device_serial, exc)
            return False

    @activity.defn
    async def execute_extract(self, inp: ExtractInput) -> ExtractResult:
        """
        Execute an 'extract' step (fb_posts / text_nodes / fb_comments strategies).

        Returns updated context (posts, text_nodes, comments, _no_new_streak) and
        break_requested flag when stop_if_no_new triggers.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        step = _prepare_activity_step(dict(inp.step))
        idx = inp.step_index
        activity.heartbeat(f"extract:{idx}:{step.get('strategy', 'fb_posts')}")

        # Work on a deep-enough copy so we never mutate the input.
        # Lists (posts, text_nodes) are copied explicitly to prevent shared-reference mutation.
        ctx: dict[str, Any] = {}
        for _k, _v in inp.context.items():
            ctx[_k] = list(_v) if isinstance(_v, list) else _v
        ctx.setdefault("posts", [])
        ctx.setdefault("comments", [])

        strategy = str(step.get("strategy", "fb_posts"))
        from tasks.scenario.steps.extraction import EDGE_CONTENT_STRATEGIES

        if strategy in EDGE_CONTENT_STRATEGIES:
            from db.database import activity_session
            from services.content.campaign_ref import resolve_persist_campaign_id

            edge_result: dict[str, Any] = {}
            async with activity_session() as db:
                persist_campaign_id = await resolve_persist_campaign_id(
                    db,
                    campaign_id=inp.campaign_id,
                    execution_id=inp.execution_id or inp.run_id,
                )
            scenario_meta = {
                "_campaign_id": persist_campaign_id,
                "_campaign_id_resolved": True,
                "_execution_id": inp.execution_id or inp.run_id,
                "_run_hash_scope": inp.execution_id or inp.run_id,
                "_campaign_vars": {"__USER_ID__": inp.user_id} if inp.user_id else {},
                "__USER_ID__": inp.user_id,
                "name": inp.scenario_config.get("name") or inp.scenario_config.get("scenario_name"),
            }
            from tasks.scenario.steps.extraction import request_edge_extra_data

            async def _wait_until_unpaused() -> None:
                if not inp.execution_id:
                    return
                from services.execution_pause_flags import is_execution_paused_async

                while await is_execution_paused_async(inp.execution_id):
                    _safe_activity_heartbeat(f"extract:{idx}:paused")
                    await asyncio.sleep(0.5)

            while True:
                edge_result = {}
                cancel_event = threading.Event()
                stop_reason = {"reason": ""}

                async def _pause_monitor() -> None:
                    if not inp.execution_id:
                        return
                    from services.execution_pause_flags import (
                        is_execution_cancelled_async,
                        is_execution_paused_async,
                    )

                    while not cancel_event.is_set():
                        if activity.is_cancelled():
                            stop_reason["reason"] = "cancelled"
                            cancel_event.set()
                            return
                        if await is_execution_cancelled_async(inp.execution_id):
                            stop_reason["reason"] = "cancelled"
                            cancel_event.set()
                            return
                        if await is_execution_paused_async(inp.execution_id):
                            stop_reason["reason"] = "paused"
                            cancel_event.set()
                            return
                        await asyncio.sleep(0.5)

                pause_task = asyncio.create_task(_pause_monitor())
                try:
                    handled = await _to_thread_with_heartbeat(
                        request_edge_extra_data,
                        device=device,
                        serial=inp.device_serial,
                        ctx=ctx,
                        scenario=scenario_meta,
                        step=step,
                        strategy=strategy,
                        result=edge_result,
                        cancel_event=cancel_event,
                        cooperative_cancel_event=cancel_event,
                        execution_id=inp.execution_id,
                    )
                finally:
                    pause_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pause_task

                if edge_result.get("cancelled") and stop_reason.get("reason") == "paused":
                    await _wait_until_unpaused()
                    continue
                break
            if handled:
                return ExtractResult(
                    ok=bool(edge_result.get("ok", True)),
                    message=str(edge_result.get("message") or ""),
                    context=ctx,
                    details={k: v for k, v in edge_result.items() if k not in {"ok", "message"}},
                )
            return ExtractResult(
                ok=False,
                message=(
                    f"extract {strategy}: device_farm content XML parser was removed; "
                    "enable edge_extra_data so phone/APK sends XML to agent-boot"
                ),
                context=ctx,
            )

        return ExtractResult(
            ok=False,
            message=f"extract: unknown strategy {strategy!r}",
            context=ctx,
        )

    @activity.defn
    async def execute_save_extraction(self, inp: SaveExtractionInput) -> StepResult:
        """
        Execute a 'save_extraction' step as a native async activity.

        Unlike the TaskQueue path (which uses asyncio.run in a thread),
        this activity is fully async and safe with the asyncpg connection pool.
        """
        _validate_serial(inp.device_serial)
        step = _prepare_activity_step(dict(inp.step))
        idx = inp.step_index
        activity.heartbeat(f"save_extraction:{idx}")

        data_var = step.get("data_var", "")
        if not data_var:
            return StepResult(
                index=idx, step_type="save_extraction", ok=False,
                message="save_extraction: missing data_var",
            )

        ctx = dict(inp.context)
        data = ctx.get(data_var)

        if data is None:
            return StepResult(
                index=idx, step_type="save_extraction", ok=False,
                message=f"save_extraction: variable '{data_var}' not found in context",
            )

        try:
            if not isinstance(data, (str, dict, list)):
                return StepResult(
                    index=idx, step_type="save_extraction", ok=False,
                    message=f"save_extraction: unsupported type for '{data_var}': {type(data).__name__}",
                )
            if isinstance(data, list) and data and not any(isinstance(item, dict) for item in data):
                return StepResult(
                    index=idx,
                    step_type="save_extraction",
                    ok=False,
                    message=f"save_extraction: variable '{data_var}' is a list but has no object items",
                )

            offsets = ctx.get("__save_extraction_offsets__", {})
            from services.execution.preview_collection import resolve_content_collection

            coll = resolve_content_collection(
                step,
                campaign_vars=getattr(inp, "campaign_vars", None) or {},
            )
            platform = step.get("platform")
            ctype = step.get("content_type")
            if not ctype:
                return StepResult(
                    index=idx, step_type="save_extraction", ok=False,
                    message="save_extraction: content_type is required (platform-qualified, e.g. fb_post)",
                )
            from services.content.legacy_type_map import qualify_content_type

            ctype = qualify_content_type(ctype, platform=platform) or ctype
            dedupe_field = step.get("dedupe_field")
            tags = step.get("tags", "")
            parent_id_var = step.get("parent_id_var")
            parent_id = ctx.get(parent_id_var) if parent_id_var else None
            item_level = int(step.get("item_level") or 0)
            from db.database import activity_session
            from services.content.campaign_ref import resolve_persist_campaign_id

            async with activity_session() as db:
                persist_campaign_id = await resolve_persist_campaign_id(
                    db,
                    campaign_id=inp.campaign_id,
                    execution_id=inp.execution_id,
                )
            report, updated_offsets = await persist_data_items(
                data=data,
                data_var=data_var,
                offsets=offsets,
                collection=coll,
                platform=platform,
                content_type=ctype,
                dedupe_field=dedupe_field,
                tags=tags,
                device_serial=inp.device_serial,
                campaign_id=persist_campaign_id,
                execution_id=inp.execution_id,
                parent_id=parent_id,
                item_level=item_level,
                user_id=inp.user_id,
            )
            ok = not (
                report.error_count > 0
                and report.saved_count == 0
                and report.duplicate_count == 0
            )
            msg = (
                f"save_extraction: saved={report.saved_count}, "
                f"duplicate={report.duplicate_count}, errors={report.error_count}"
            )
            if not ok:
                msg = "save_extraction: all items failed"

            return StepResult(
                index=idx, step_type="save_extraction", ok=ok, message=msg,
                details={
                    "saved_count": report.saved_count,
                    "duplicate_count": report.duplicate_count,
                    "error_count": report.error_count,
                    "updated_offsets": updated_offsets,
                },
            )

        except Exception as exc:
            log.error("[%s] execute_save_extraction error: %s", inp.device_serial, exc)
            return StepResult(
                index=idx, step_type="save_extraction", ok=False,
                message=f"save_extraction failed: {exc}",
            )

    @activity.defn
    async def evaluate_condition(self, inp: ConditionCheckInput) -> bool:
        """
        Evaluate a repeat_until stop condition.

        Uses _eval_ru_condition from scenario_task.py for consistency.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        activity.heartbeat("evaluate_condition")

        try:
            from tasks.scenario_task import _eval_ru_condition
            from common.variable_resolver import VariableContext

            # Build a VariableContext with runtime vars for condition evaluation
            var_ctx = VariableContext(
                device_serial=inp.device_serial,
                device_model=getattr(device, "model", ""),
            )
            # Inject runtime vars
            for name, value in inp.runtime_vars.items():
                var_ctx.set(name, value)

            return _eval_ru_condition(device, inp.condition, var_ctx)
        except Exception as exc:
            log.warning("evaluate_condition error: %s", exc)
            return False

    @activity.defn
    async def finalize_campaign(self, inp: dict) -> None:
        """Update Execution + Campaign DB status when a workflow ends.

        Called at the end of ScenarioWorkflow.run (success, failure, or cancel).
        - When all workflows for the campaign are done, sets Campaign.status = "idle".

        Accepts a dict: {"campaign_id": str, "execution_id": str|None, "success": bool}
        (kept as dict for Temporal serialization simplicity).
        """
        # Support both old str payload (backward compat) and new dict payload.
        if isinstance(inp, str):
            campaign_id: str = inp
            success = True
            execution_id = None
            device_serial = None
            step_results: list = []
            workflow_failed_message = None
        else:
            campaign_id = inp.get("campaign_id", "")
            success = bool(inp.get("success", True))
            # run_id is legacy alias for execution_id
            execution_id = inp.get("execution_id") or inp.get("run_id")
            device_serial = inp.get("device_serial")
            step_results = inp.get("step_results") or []
            workflow_failed_message = (inp.get("failed_message") or "").strip() or None

        activity.heartbeat("finalize_campaign")

        # Persist per-device execution result
        if execution_id and device_serial:
            try:
                from datetime import datetime, timezone as _tz
                from db.database import activity_session
                from db.crud.execution import (
                    cancel_execution_record,
                    get_execution,
                    update_execution,
                    upsert_execution_result,
                )
                from db.crud.device import get_device_by_serial
                from services.execution.step_store import (
                    execution_step_to_legacy_dict,
                    persist_execution_steps_from_results,
                    slim_step_results,
                )
                er_status = "passed" if success else "failed"
                passed_steps: list[dict[str, Any]] = []
                failed_steps: list[dict[str, Any]] = []
                _device_id = None
                async with activity_session() as db:
                    from services.execution.event_publisher import resolve_execution_org_id
                    from tenancy.context import tenant_context

                    org_id_epic = ""
                    if isinstance(inp, dict):
                        org_id_epic = (inp.get("org_id") or "").strip()
                    ex_row = await get_execution(db, execution_id)
                    if not org_id_epic and ex_row:
                        org_id_epic = await resolve_execution_org_id(db, ex_row)
                    if not org_id_epic:
                        raise RuntimeError(
                            f"finalize_campaign: no org_id for execution {execution_id}"
                        )

                    campaign_row = None
                    device = None
                    with tenant_context(org_id_epic):
                        execution_campaign_id = getattr(ex_row, "campaign_id", None) if ex_row else None
                        execution_user_id = getattr(ex_row, "user_id", None) if ex_row else None
                        if execution_campaign_id:
                            from db.crud import campaign_entity as campaign_entity_repo

                            campaign_row = await campaign_entity_repo.get_campaign_entity(
                                db, execution_campaign_id
                            )
                        device = await get_device_by_serial(db, device_serial)
                        if device:
                            _device_id = device.id
                            finished_at = datetime.now(_tz.utc)
                            try:
                                await persist_execution_steps_from_results(
                                    db,
                                    execution_id=execution_id,
                                    step_results=step_results,
                                    default_ended_at=finished_at,
                                )
                            except Exception as exc:
                                log.warning(
                                    "finalize_campaign: execution_steps persist failed "
                                    "(%s/%s): %s",
                                    execution_id,
                                    device_serial,
                                    exc,
                                )
                            if not success and not step_results:
                                try:
                                    from db.crud.execution_steps import list_execution_steps

                                    persisted_rows = await list_execution_steps(db, execution_id)
                                    persisted_step_results = [
                                        execution_step_to_legacy_dict(row)
                                        for row in persisted_rows
                                    ]
                                except Exception as exc:
                                    log.warning(
                                        "finalize_campaign: execution_steps fallback read failed "
                                        "(%s/%s): %s",
                                        execution_id,
                                        device_serial,
                                        exc,
                                    )
                                    persisted_step_results = []
                                step_results = _finalize_step_results(
                                    success=success,
                                    step_results=step_results,
                                    persisted_step_results=persisted_step_results,
                                )
                            else:
                                step_results = _finalize_step_results(
                                    success=success,
                                    step_results=step_results,
                                    persisted_step_results=[],
                                )
                            passed_steps = slim_step_results(
                                [s for s in step_results if s.get("ok")]
                            )
                            failed_steps = slim_step_results(
                                [s for s in step_results if not s.get("ok")]
                            )
                            if execution_campaign_id:
                                from services.campaign.events import emit_campaign_step_warning

                                campaign_name = (
                                    getattr(campaign_row, "name", None)
                                    if campaign_row is not None
                                    else None
                                )
                                for warning in _ignored_step_warnings_from_results(step_results):
                                    await emit_campaign_step_warning(
                                        db,
                                        org_id=org_id_epic,
                                        campaign_id=execution_campaign_id,
                                        campaign_name=campaign_name,
                                        execution_id=execution_id,
                                        device_serial=device_serial,
                                        step_index=warning.get("step_index"),
                                        step_type=str(warning.get("step_type") or "unknown"),
                                        message=str(warning.get("message") or "step warning"),
                                        user_id=execution_user_id,
                                    )
                            cancelled_terminal = (
                                not success
                                and _finalize_is_cancelled(
                                    failed_steps=failed_steps,
                                    workflow_failed_message=workflow_failed_message,
                                )
                            )
                            await upsert_execution_result(
                                db,
                                execution_id=execution_id,
                                device_id=device.id,
                                status=er_status,
                                passed_steps=passed_steps,
                                failed_steps=failed_steps,
                                finished_at=finished_at,
                            )
                            terminal = (
                                "completed" if success
                                else "cancelled" if cancelled_terminal
                                else "dlq_open"
                            )
                            if cancelled_terminal:
                                await cancel_execution_record(
                                    db,
                                    execution_id,
                                    reason=workflow_failed_message or "workflow_cancelled",
                                )
                            elif not success:
                                from services.campaign.dlq_service import open_dlq_for_failed_execution

                                error_msg = _finalize_error_message(
                                    failed_steps=failed_steps,
                                    workflow_failed_message=workflow_failed_message,
                                )
                                await open_dlq_for_failed_execution(
                                    db,
                                    execution_id=execution_id,
                                    device_serial=device_serial,
                                    step_results=step_results,
                                    error_msg=error_msg,
                                    org_id=org_id_epic,
                                    user_id=execution_user_id,
                                )
                            elif ex_row and getattr(ex_row, "status", None) not in ("cancelled", "paused"):
                                await update_execution(db, execution_id, status=terminal)
                                from services.execution.event_publisher import (
                                    enqueue_execution_event,
                                    process_outbox_batch,
                                )
                                from services.execution.event_types import EXECUTION_COMPLETED

                                await enqueue_execution_event(
                                    db,
                                    event_type=EXECUTION_COMPLETED,
                                    execution_id=execution_id,
                                    organization_id=org_id_epic,
                                    campaign_id=execution_campaign_id,
                                    payload={"device_serial": device_serial},
                                    execution=ex_row,
                                )
                                await process_outbox_batch(db)
                            if ex_row and (getattr(ex_row, "meta", {}) or {}).get("dispatch_source"):
                                from services.campaign.dispatcher import finish_fan_out_execution
                                from services.campaign.execution_runtime import (
                                    maybe_promote_sequential_execution,
                                )

                                await finish_fan_out_execution(
                                    db,
                                    ex_row,
                                    org_id=org_id_epic,
                                    actor_user_id=execution_user_id or "system",
                                    status=terminal,
                                )
                                temporal_client = None
                                if _temporal_config and getattr(_temporal_config, "enabled", False):
                                    try:
                                        from temporal.worker import get_temporal_client

                                        temporal_client = await get_temporal_client(_temporal_config)
                                    except Exception:
                                        pass
                                if campaign_row is not None:
                                    await maybe_promote_sequential_execution(
                                        db,
                                        ex_row,
                                        campaign=campaign_row,
                                        org_id=org_id_epic,
                                        actor_user_id=execution_user_id or "system",
                                        temporal_client=temporal_client,
                                        temporal_config=_temporal_config,
                                        manager=None,
                                    )
                                await db.commit()
                                return
                            await db.commit()
                    # Account usage end + timeline event
                    if device_serial:
                        try:
                            from services.account_manager import end_account_usage

                            async with activity_session() as udb:
                                ex = await get_execution(udb, execution_id)
                                if ex:
                                    usage_map = (ex.meta or {}).get("account_usage") or {}
                                    info = usage_map.get(device_serial)
                                    if info and info.get("account_id"):
                                        started_raw = info.get("started_at")
                                        duration_min = 0.0
                                        if started_raw:
                                            from datetime import datetime, timezone as _tz2
                                            started = datetime.fromisoformat(
                                                str(started_raw).replace("Z", "+00:00")
                                            )
                                            duration_min = max(
                                                0.0,
                                                (
                                                    datetime.now(_tz2.utc) - started
                                                ).total_seconds()
                                                / 60.0,
                                            )
                                        with tenant_context(org_id_epic):
                                            await end_account_usage(
                                                str(info["account_id"]),
                                                duration_min,
                                                device_serial=device_serial,
                                                entity_type="execution",
                                                entity_id=execution_id,
                                                end_reason="passed" if success else "failed",
                                            )
                        except Exception as usage_exc:
                            log.warning(
                                "finalize_campaign: account usage end failed (%s): %s",
                                device_serial,
                                usage_exc,
                            )
                log.info(
                    "finalize_campaign: execution_result %s/%s → %s",
                    execution_id, device_serial, er_status,
                )
                # Webhook: fire-and-forget notification
                org_id = inp.get("org_id") if isinstance(inp, dict) else None
                if org_id:
                    from services.webhook_dispatcher import dispatch_webhook
                    event = "task.complete" if success else "task.failed"
                    await dispatch_webhook(org_id, event, {
                        "execution_id": execution_id,
                        "device_serial": device_serial,
                        "status": er_status,
                        "passed_steps": len(passed_steps),
                        "failed_steps": len(failed_steps),
                    })
            except Exception as exc:
                log.warning(
                    "finalize_campaign: execution_result update failed (%s/%s): %s",
                    execution_id, device_serial, exc,
                )

        if not campaign_id:
            return

        if execution_id:
            try:
                from db.database import activity_session
                from db.crud.execution import get_execution

                async with activity_session() as db:
                    ex_row = await get_execution(db, execution_id)
                    if ex_row and (getattr(ex_row, "meta", {}) or {}).get("dispatch_source"):
                        return
            except Exception:
                pass

        cfg = _temporal_config
        if cfg is None:
            log.warning("finalize_campaign: no temporal config, skipping campaign status update")
            return
        try:
            from temporal.worker import get_temporal_client
            client = await get_temporal_client(cfg)
            # This activity runs *while* the parent ScenarioWorkflow is still in
            # ExecutionStatus=Running (it awaits this activity before return).
            # Without excluding the caller, list_workflows always sees ≥1 match
            # and the campaign never flips back to idle in the DB.
            try:
                caller_wf_id = activity.info().workflow_id or ""
            except Exception:
                caller_wf_id = ""
            wf_query = (
                f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" '
                f'AND ExecutionStatus="Running"'
            )
            still_running = 0
            async for wf_exec in client.list_workflows(wf_query):
                if caller_wf_id and wf_exec.id == caller_wf_id:
                    continue
                still_running += 1
                break  # one other running workflow is enough
            if still_running == 0:
                from db.crud.campaign_entity import lookup_campaign_org_id
                from db.database import activity_session
                from db.crud.campaign import update_campaign_status
                from tenancy.context import tenant_context

                async with activity_session() as db:
                    camp_org = await lookup_campaign_org_id(db, campaign_id)
                    if not camp_org:
                        log.warning(
                            "finalize_campaign: campaign %s not found, skipping idle update",
                            campaign_id,
                        )
                        return
                    with tenant_context(camp_org):
                        await update_campaign_status(db, campaign_id, "idle")
                        await db.commit()
                log.info("finalize_campaign: campaign %s → idle", campaign_id)
        except Exception as exc:
            log.warning("finalize_campaign error (campaign %s): %s", campaign_id, exc)


def _xml_has_element(xml: str, by: str, value: str) -> bool:
    """Check if XML hierarchy contains element matching (by, value).

    Uses attribute iteration instead of XPath f-string interpolation
    to prevent XPath injection when value contains quotes.
    """
    if not xml or not value:
        return False
    try:
        root = ET.fromstring(xml)
        attr_map = {
            "text": "text",
            "resource-id": "resource-id",
            "content-desc": "content-desc",
            "accessibility id": "content-desc",
            "class name": "class",
        }
        attr = attr_map.get(by)
        if attr:
            return any(node.get(attr) == value for node in root.iter())
        for node in root.iter():
            if node.get("text") == value or node.get("resource-id") == value:
                return True
        return False
    except Exception:
        return False
