"""
services/scheduler.py — SchedulerService: schedule lifecycle management (DF-008).

Two execution modes:
- Temporal mode (preferred): Temporal Schedules API handles cron triggering.
  Durable, observable, supports pause/resume/trigger from Temporal UI.
- Fallback mode: SchedulerEngine polls every 30s using croniter.
  Used when Temporal is disabled (config.temporal.enabled = False).

API:
    service = SchedulerService(temporal_client, manager, queue)
    await service.create(db, schedule_id, data, user_id)
    await service.update(db, schedule_id, patch)
    await service.delete(db, schedule_id)
    await service.toggle(db, schedule_id, enabled)
    run_id = await service.trigger_now(db, schedule_id)

SchedulerEngine (fallback):
    engine = SchedulerEngine(queue, manager)
    await engine.start()  # runs as background asyncio task
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.idempotency import (
    claim_or_get_intent,
    make_idempotency_key,
    mark_intent_accepted,
    mark_intent_failed,
)

log = logging.getLogger(__name__)

# Per-schedule in-process locks. Even with atomic DB claim, a single process
# that both polls AND receives trigger_now() can still race; the asyncio.Lock
# serializes any concurrent execution path within one server.
_SCHEDULE_LOCKS: Dict[str, asyncio.Lock] = {}
_SCHEDULE_LOCKS_GUARD = threading.Lock()


def _schedule_lock_for(schedule_id: str) -> asyncio.Lock:
    with _SCHEDULE_LOCKS_GUARD:
        lock = _SCHEDULE_LOCKS.get(schedule_id)
        if lock is None:
            lock = asyncio.Lock()
            _SCHEDULE_LOCKS[schedule_id] = lock
        return lock

_TEMPORAL_SCHEDULE_PREFIX = "df-schedule-"
_TEMPORAL_WORKFLOW_PREFIX = "df-sched-run-"


# ── Cron helpers ──────────────────────────────────────────────────────────────


def compute_next_run(
    cron_expression: str,
    timezone_name: str = "Asia/Ho_Chi_Minh",
    base: Optional[datetime] = None,
) -> Optional[datetime]:
    """
    Compute the next run datetime using croniter.

    Returns UTC datetime or None if croniter is not installed / expression invalid.
    """
    try:
        from croniter import croniter
        import pytz

        if base is None:
            base = datetime.now(timezone.utc)

        tz = pytz.timezone(timezone_name)
        base_local = base.astimezone(tz)
        cron = croniter(cron_expression, base_local)
        next_dt: datetime = cron.get_next(datetime)
        return next_dt.astimezone(timezone.utc)
    except Exception as exc:
        log.warning("compute_next_run failed (cron=%r): %s", cron_expression, exc)
        return None


def validate_cron(cron_expression: str) -> bool:
    """Return True if the cron expression is valid."""
    try:
        from croniter import croniter
        return croniter.is_valid(cron_expression)
    except Exception:
        return False


# ── SchedulerService ──────────────────────────────────────────────────────────


class SchedulerService:
    """
    Manages schedule lifecycle: DB persistence + Temporal Schedule sync.

    temporal_client=None means Temporal mode is unavailable;
    operations still work but scheduling falls back to SchedulerEngine.
    """

    def __init__(
        self,
        temporal_client,
        manager,
        queue,
        temporal_config=None,
    ) -> None:
        self._client = temporal_client
        self._manager = manager
        self._queue = queue
        self._cfg = temporal_config

    # ── Public API ────────────────────────────────────────────────────────────

    async def create(
        self,
        db,
        *,
        name: str,
        description: str = "",
        target_type: str,
        target_id: Optional[str] = None,
        inline_steps: Optional[list] = None,
        inline_variables: Optional[dict] = None,
        device_group_id: Optional[str] = None,
        filter_state: str = "READY",
        filter_model: Optional[str] = None,
        max_devices: Optional[int] = None,
        cron_expression: str,
        timezone_name: str = "Asia/Ho_Chi_Minh",
        random_delay_min: int = 0,
        random_delay_max: int = 0,
        stagger_devices: bool = False,
        stagger_interval_seconds: int = 60,
        is_enabled: bool = True,
        user_id: Optional[str] = None,
    ):
        """Create schedule in DB + register Temporal Schedule if Temporal enabled."""
        from db.crud.schedule import create_schedule

        next_run_at = compute_next_run(cron_expression, timezone_name) if is_enabled else None

        schedule = await create_schedule(
            db,
            name=name,
            description=description,
            target_type=target_type,
            target_id=target_id,
            inline_steps=inline_steps,
            inline_variables=inline_variables,
            device_group_id=device_group_id,
            filter_state=filter_state,
            filter_model=filter_model,
            max_devices=max_devices,
            cron_expression=cron_expression,
            timezone_name=timezone_name,
            random_delay_min=random_delay_min,
            random_delay_max=random_delay_max,
            stagger_devices=stagger_devices,
            stagger_interval_seconds=stagger_interval_seconds,
            is_enabled=is_enabled,
            next_run_at=next_run_at,
            user_id=user_id,
        )
        await db.commit()

        if self._client is not None and is_enabled:
            await self._create_temporal_schedule(schedule.id, cron_expression, timezone_name)
        else:
            log.debug(
                "[scheduler] schedule %s created without Temporal (fallback mode)", schedule.id
            )

        return schedule

    async def update(self, db, schedule_id: str, patch: dict) -> Any:
        """Update schedule in DB + sync Temporal Schedule spec if cron changed."""
        from db.crud.schedule import update_schedule, get_schedule

        cron = patch.get("cron_expression")
        tz_name = patch.get("timezone_name", "Asia/Ho_Chi_Minh")

        if cron:
            patch.setdefault("next_run_at", compute_next_run(cron, tz_name))

        schedule = await update_schedule(db, schedule_id, **patch)
        if schedule is None:
            return None
        await db.commit()

        if cron and self._client is not None:
            await self._update_temporal_schedule_spec(
                schedule_id, cron, schedule.timezone
            )

        return schedule

    async def delete(self, db, schedule_id: str) -> bool:
        """Delete schedule from DB + remove from Temporal if present."""
        from db.crud.schedule import delete_schedule

        deleted = await delete_schedule(db, schedule_id)
        if not deleted:
            return False
        await db.commit()

        if self._client is not None:
            await self._delete_temporal_schedule(schedule_id)

        return True

    async def toggle(self, db, schedule_id: str, enabled: bool) -> Any:
        """Enable or disable a schedule."""
        from db.crud.schedule import update_schedule, get_schedule

        schedule = await get_schedule(db, schedule_id)
        if schedule is None:
            return None

        next_run = (
            compute_next_run(schedule.cron_expression, schedule.timezone)
            if enabled
            else None
        )
        schedule = await update_schedule(
            db, schedule_id, is_enabled=enabled, next_run_at=next_run
        )
        await db.commit()

        if self._client is not None:
            await self._set_temporal_schedule_paused(schedule_id, paused=not enabled)

        return schedule

    async def trigger_now(self, db, schedule_id: str) -> str:
        """
        Trigger a schedule immediately (bypass cron timing).

        Returns the run_id created.
        """
        from db.crud.schedule import get_schedule, create_schedule_run

        schedule = await get_schedule(db, schedule_id)
        if schedule is None:
            raise ValueError(f"Schedule {schedule_id!r} not found")

        if self._client is not None:
            # Temporal: trigger the existing schedule handle
            handle = self._client.get_schedule_handle(
                f"{_TEMPORAL_SCHEDULE_PREFIX}{schedule_id}"
            )
            try:
                await handle.trigger()
                log.info("[scheduler] triggered Temporal schedule %s", schedule_id)
            except Exception as exc:
                log.warning("[scheduler] Temporal trigger failed, falling back: %s", exc)
                return await self._trigger_fallback(db, schedule)
        else:
            return await self._trigger_fallback(db, schedule)

        # Create a pending run record for UI tracking
        run = await create_schedule_run(db, schedule_id=schedule_id, status="pending")
        await db.commit()
        return run.id

    async def _trigger_fallback(self, db, schedule) -> str:
        """Direct dispatch when Temporal is not available."""
        from db.crud.schedule import create_schedule_run

        # Serialize with SchedulerEngine's poll loop on this schedule_id to
        # prevent manual trigger racing an in-flight fallback dispatch.
        lock = _schedule_lock_for(schedule.id)
        await lock.acquire()
        try:
            # Idempotency claim. Manual trigger uses a timestamp-bucketed key
            # so two rapid-fire trigger clicks collapse, but distinct firings
            # (minutes apart) each get their own intent.
            now_bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
            intent_source = f"schedule:{schedule.id}:trigger:{now_bucket}"
            intent = None
            try:
                intent = await claim_or_get_intent(
                    key=make_idempotency_key(intent_source, {"id": schedule.id}),
                    source=intent_source,
                    payload={"schedule_id": schedule.id, "bucket": now_bucket},
                )
                if intent.replay and intent.result_ref:
                    log.info(
                        "[scheduler] trigger_now schedule %s deduped — run=%s",
                        schedule.id, intent.result_ref,
                    )
                    return intent.result_ref
            except Exception as exc:
                log.warning(
                    "[scheduler] idempotency claim failed for trigger, proceeding: %s", exc
                )

            run = await create_schedule_run(db, schedule_id=schedule.id, status="running")
            await db.commit()
            try:
                run_id = await self._trigger_fallback_body(db, schedule, run)
                if intent is not None:
                    try:
                        await mark_intent_accepted(intent.id, result_ref=str(run.id))
                    except Exception as mk_exc:
                        log.warning("[scheduler] mark_intent_accepted failed: %s", mk_exc)
                return run_id
            except Exception as exc:
                if intent is not None:
                    try:
                        await mark_intent_failed(intent.id, reason=str(exc))
                    except Exception as mk_exc:
                        log.warning("[scheduler] mark_intent_failed failed: %s", mk_exc)
                raise
        finally:
            lock.release()

    async def _trigger_fallback_body(self, db, schedule, run) -> str:
        """Execute the dispatch and persist run state.

        Re-raises on dispatch failure so the caller can mark the idempotency
        intent as failed. The schedule_run row is updated in both paths so the
        UI still reflects reality even when we re-raise.
        """
        from db.crud.schedule import update_schedule_run
        from db.crud.schedule import update_schedule_after_run
        from db.database import AsyncSessionLocal

        cfg = {
            "id": schedule.id,
            "target_type": schedule.target_type,
            "target_id": schedule.target_id,
            "inline_steps": schedule.inline_steps,
            "inline_variables": schedule.inline_variables or {},
            "user_id": str(schedule.user_id) if schedule.user_id else None,
            "device_group_id": schedule.device_group_id,
            "filter_state": schedule.filter_state,
            "filter_model": schedule.filter_model,
            "max_devices": schedule.max_devices,
            "stagger_devices": schedule.stagger_devices,
            "stagger_interval_seconds": schedule.stagger_interval_seconds,
        }

        try:
            result = await _dispatch_schedule_config(
                cfg, queue=self._queue, manager=self._manager,
            )
        except Exception as exc:
            log.error("[scheduler] fallback dispatch error: %s", exc)
            failed_at = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as udb:
                await update_schedule_run(
                    udb, run.id,
                    status="failed",
                    finished_at=failed_at,
                    error_message=str(exc),
                )
                await update_schedule_after_run(
                    udb, schedule.id,
                    last_run_at=failed_at,
                    next_run_at=compute_next_run(
                        schedule.cron_expression, schedule.timezone, base=failed_at
                    ),
                )
                await udb.commit()
            raise

        finished_at = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as udb:
            await update_schedule_run(
                udb, run.id,
                status="completed",
                finished_at=finished_at,
                devices_dispatched=result.get("devices_dispatched", 0),
                task_ids=result.get("task_ids", []),
            )
            await update_schedule_after_run(
                udb, schedule.id,
                last_run_at=finished_at,
                next_run_at=compute_next_run(
                    schedule.cron_expression, schedule.timezone, base=finished_at
                ),
            )
            await udb.commit()
        return run.id

    # ── Temporal Schedule sync ────────────────────────────────────────────────

    async def _create_temporal_schedule(
        self, schedule_id: str, cron_expression: str, timezone_name: str
    ) -> None:
        """Register a Temporal Schedule that triggers ScheduleRunWorkflow."""
        try:
            from temporalio.client import (
                Schedule,
                ScheduleActionStartWorkflow,
                ScheduleSpec,
                ScheduleState,
            )
            from temporalio.common import SearchAttributeKey, WorkflowIDReusePolicy
            from temporal.schedule_workflow import ScheduleRunWorkflow
            from temporal.schedule_shared import ScheduleRunInput
            from temporal.shared import TASK_QUEUE_NAME

            task_queue = TASK_QUEUE_NAME
            if self._cfg:
                task_queue = getattr(self._cfg, "task_queue", None) or task_queue

            temporal_id = f"{_TEMPORAL_SCHEDULE_PREFIX}{schedule_id}"
            workflow_id_prefix = f"{_TEMPORAL_WORKFLOW_PREFIX}{schedule_id}"

            await self._client.create_schedule(
                temporal_id,
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        ScheduleRunWorkflow.run,
                        ScheduleRunInput(schedule_id=schedule_id),
                        id=workflow_id_prefix,
                        task_queue=task_queue,
                        # ALLOW_DUPLICATE lets each scheduled fire start a new workflow
                        # even if a previous run with the same prefix-id is still running
                        # or completed — prevents ID collision on repeated firings.
                        workflow_id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    ),
                    spec=ScheduleSpec(
                        cron_expressions=[cron_expression],
                        time_zone_name=timezone_name,
                    ),
                ),
            )
            log.info(
                "[scheduler] Temporal schedule created: %s cron=%r tz=%s",
                temporal_id, cron_expression, timezone_name,
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "already exists" in exc_str or "already_exists" in exc_str:
                # Temporal schedule already registered — treat as success.
                log.info("[scheduler] Temporal schedule %s already exists, skipping create", schedule_id)
            else:
                # Unexpected error — the schedule will NOT fire until this is resolved.
                log.error(
                    "[scheduler] create_temporal_schedule failed for %s: %s — "
                    "schedule will not fire until Temporal registration succeeds",
                    schedule_id, exc,
                )
                raise

    async def _update_temporal_schedule_spec(
        self, schedule_id: str, cron_expression: str, timezone_name: str
    ) -> None:
        """Update cron expression on an existing Temporal Schedule."""
        try:
            from temporalio.client import ScheduleUpdate, ScheduleSpec

            temporal_id = f"{_TEMPORAL_SCHEDULE_PREFIX}{schedule_id}"
            handle = self._client.get_schedule_handle(temporal_id)

            def _updater(input):
                schedule = input.description.schedule
                schedule.spec = ScheduleSpec(
                    cron_expressions=[cron_expression],
                    time_zone_name=timezone_name,
                )
                return ScheduleUpdate(schedule=schedule)

            await handle.update(_updater)
        except Exception as exc:
            log.warning("[scheduler] update_temporal_schedule_spec failed: %s", exc)

    async def _set_temporal_schedule_paused(
        self, schedule_id: str, paused: bool
    ) -> None:
        try:
            temporal_id = f"{_TEMPORAL_SCHEDULE_PREFIX}{schedule_id}"
            handle = self._client.get_schedule_handle(temporal_id)
            if paused:
                await handle.pause(note="Disabled via API")
            else:
                await handle.unpause(note="Enabled via API")
        except Exception as exc:
            log.warning("[scheduler] set_temporal_schedule_paused failed: %s", exc)

    async def _delete_temporal_schedule(self, schedule_id: str) -> None:
        try:
            temporal_id = f"{_TEMPORAL_SCHEDULE_PREFIX}{schedule_id}"
            handle = self._client.get_schedule_handle(temporal_id)
            await handle.delete()
        except Exception as exc:
            log.warning("[scheduler] delete_temporal_schedule failed: %s", exc)


# ── SchedulerEngine (fallback polling) ───────────────────────────────────────


class SchedulerEngine:
    """
    Background asyncio task that polls DB every 30s for due schedules.

    Used as fallback when Temporal is not enabled.
    The polling interval matches Temporal's schedule granularity.
    """

    _CHECK_INTERVAL = 30  # seconds

    def __init__(self, queue, manager) -> None:
        self._queue = queue
        self._manager = manager
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background poll loop as an asyncio task."""
        self._running = True
        self._task = asyncio.create_task(self._run(), name="scheduler-engine")
        log.info("[scheduler-engine] started (poll_interval=%ds)", self._CHECK_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("[scheduler-engine] stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                await self._check_due_schedules()
            except Exception as exc:
                log.error("[scheduler-engine] check error: %s", exc)
            await asyncio.sleep(self._CHECK_INTERVAL)

    async def _check_due_schedules(self) -> None:
        from db.database import AsyncSessionLocal
        from db.crud.schedule import claim_due_schedules

        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            # Atomic claim — advances next_run_at under row lock so another
            # poller (this process or peer) won't see the same row as due.
            due = await claim_due_schedules(db, now)

        for schedule in due:
            # Fire each schedule as a separate task (non-blocking)
            asyncio.create_task(
                self._execute_schedule(schedule),
                name=f"schedule-run-{schedule.id}",
            )

    async def _execute_schedule(self, schedule) -> None:
        # Guard against any in-process concurrency (poll overlap, manual
        # trigger_now) on the same schedule_id.
        async with _schedule_lock_for(schedule.id):
            await self._execute_schedule_locked(schedule)

    async def _execute_schedule_locked(self, schedule) -> None:
        from db.database import AsyncSessionLocal
        from db.crud.schedule import (
            create_schedule_run,
            update_schedule_run,
            update_schedule_after_run,
        )

        now = datetime.now(timezone.utc)
        run_id = None

        # Idempotency: tick-bucket the fire so replays (poll retry, concurrent
        # process claiming the same row) fold into one intent. The bucket is
        # the schedule's cron cadence — for fallback we approximate by rounding
        # to the minute, which matches the 30s poll interval.
        tick = now.replace(second=0, microsecond=0).isoformat()
        intent_source = f"schedule:{schedule.id}:tick:{tick}"
        intent = None
        try:
            intent = await claim_or_get_intent(
                key=make_idempotency_key(intent_source, {"id": schedule.id}),
                source=intent_source,
                payload={"schedule_id": schedule.id, "tick": tick},
            )
            if intent.replay:
                log.info(
                    "[scheduler] schedule %s fire skipped — intent already accepted (%s)",
                    schedule.id, intent.result_ref or "n/a",
                )
                return
        except Exception as exc:
            # If the idempotency layer is unavailable, fall back to best-effort
            # dispatch (better to double-run than miss). The schedule lock +
            # claim_due_schedules lease still give strong protection.
            log.warning("[scheduler] idempotency claim failed, proceeding: %s", exc)

        async with AsyncSessionLocal() as db:
            run = await create_schedule_run(db, schedule_id=schedule.id, status="pending")
            run_id = run.id
            await db.commit()

        # NOTE: intent stays in 'new' until dispatch actually succeeds below.
        # Accepting too early would mark a fire successful even if enqueue
        # subsequently raised, so replay logic would skip a real retry.

        # Apply random delay before executing
        delay_min = schedule.random_delay_min or 0
        delay_max = schedule.random_delay_max or 0
        if delay_max > 0 and delay_max >= delay_min:
            delay = random.randint(delay_min, delay_max)
            if delay > 0:
                await asyncio.sleep(delay)

        cfg = {
            "id": schedule.id,
            "target_type": schedule.target_type,
            "target_id": schedule.target_id,
            "inline_steps": schedule.inline_steps,
            "inline_variables": schedule.inline_variables or {},
            "user_id": str(schedule.user_id) if schedule.user_id else None,
            "device_group_id": schedule.device_group_id,
            "filter_state": schedule.filter_state,
            "filter_model": schedule.filter_model,
            "max_devices": schedule.max_devices,
            "stagger_devices": schedule.stagger_devices,
            "stagger_interval_seconds": schedule.stagger_interval_seconds,
        }

        try:
            result = await _dispatch_schedule_config(
                cfg, queue=self._queue, manager=self._manager
            )
            status = "completed"
            error = None
            if intent is not None:
                try:
                    await mark_intent_accepted(intent.id, result_ref=str(run_id))
                except Exception as mk_exc:
                    log.warning("[scheduler-engine] mark_intent_accepted failed: %s", mk_exc)
        except Exception as exc:
            log.error("[scheduler-engine] schedule %s failed: %s", schedule.id, exc)
            result = {"devices_dispatched": 0, "task_ids": []}
            status = "failed"
            error = str(exc)
            if intent is not None:
                try:
                    await mark_intent_failed(intent.id, reason=str(exc))
                except Exception as mk_exc:
                    log.warning("[scheduler-engine] mark_intent_failed failed: %s", mk_exc)

        next_run = compute_next_run(schedule.cron_expression, schedule.timezone, now)

        async with AsyncSessionLocal() as db:
            if run_id:
                await update_schedule_run(
                    db, run_id,
                    status=status,
                    finished_at=datetime.now(timezone.utc),
                    devices_dispatched=result.get("devices_dispatched", 0),
                    task_ids=result.get("task_ids", []),
                    error_message=error,
                )
            await update_schedule_after_run(
                db, schedule.id,
                last_run_at=now,
                next_run_at=next_run,
            )
            await db.commit()


# ── Shared dispatch logic ─────────────────────────────────────────────────────


async def _dispatch_schedule_config(
    cfg: dict[str, Any],
    *,
    queue,
    manager,
    temporal_client=None,
    temporal_config=None,
) -> dict[str, Any]:
    """
    Dispatch a schedule config to devices.

    Used by both SchedulerEngine (fallback) and SchedulerService.trigger_now.
    """
    target_type = cfg["target_type"]

    if target_type == "campaign":
        return await _dispatch_campaign(cfg, queue, temporal_client, temporal_config)
    elif target_type == "template":
        return await _dispatch_template(cfg, queue, manager)
    elif target_type == "fleet":
        return await _dispatch_fleet(cfg, queue, manager)
    else:
        raise ValueError(f"Unknown target_type: {target_type!r}")


async def _dispatch_campaign(
    cfg: dict,
    queue,
    temporal_client,
    temporal_config,
) -> dict[str, Any]:
    target_id = cfg.get("target_id")
    if not target_id:
        raise ValueError("campaign dispatch requires target_id")

    if temporal_client is None:
        raise RuntimeError(
            f"Temporal is required for campaign dispatch (campaign_id={target_id!r}). "
            "Ensure temporal.enabled=true and the Temporal server is reachable."
        )

    from services.campaign_dispatch import enqueue_campaign_run_temporal
    result, _ = await enqueue_campaign_run_temporal(
        target_id, temporal_client, temporal_config
    )

    return {
        "devices_dispatched": len(result.get("device_serials", [])),
        "workflow_ids": result.get("workflow_ids", []),
    }


async def _dispatch_template(
    cfg: dict,
    queue,
    manager,
) -> dict[str, Any]:
    """Load template steps then dispatch as fleet."""
    from db.database import AsyncSessionLocal
    from db.models.scenario_template import ScenarioTemplate
    from sqlalchemy import select

    target_id = cfg.get("target_id")
    if not target_id:
        raise ValueError("template dispatch requires target_id")

    async with AsyncSessionLocal() as db:
        result_q = await db.execute(
            select(ScenarioTemplate).where(ScenarioTemplate.id == target_id)
        )
        template = result_q.scalar_one_or_none()

    if template is None:
        raise ValueError(f"ScenarioTemplate {target_id!r} not found")

    fleet_cfg = {
        **cfg,
        "inline_steps": template.steps,
        "inline_variables": template.variables or {},
    }
    return await _dispatch_fleet(fleet_cfg, queue, manager)


async def _dispatch_fleet(
    cfg: dict,
    queue,
    manager,
) -> dict[str, Any]:
    """Dispatch inline steps to all matching devices."""
    from db.database import AsyncSessionLocal
    from db.crud.scenario_template import list_templates
    from db.crud.device_group import list_group_devices
    from services.campaign_dispatch import _build_scenario_registry
    from runtime.core import Task
    from tasks.scenario_task import make_scenario_task
    from temporal.schedule_activities import _make_staggered_task

    steps = cfg.get("inline_steps") or []
    if not steps:
        raise ValueError("fleet dispatch requires inline_steps")

    variables = cfg.get("inline_variables") or {}
    device_group_id = cfg.get("device_group_id")
    filter_state = cfg.get("filter_state", "READY")
    filter_model = cfg.get("filter_model")
    max_devices = cfg.get("max_devices")
    stagger = cfg.get("stagger_devices", False)
    stagger_interval = int(cfg.get("stagger_interval_seconds", 60))

    # Resolve devices
    all_devices = list(manager.all_devices()) if manager else []
    if device_group_id:
        async with AsyncSessionLocal() as db:
            group_devices = await list_group_devices(db, device_group_id)
        serials = {d.serial for d in group_devices}
        devices = [d for d in all_devices if d.serial in serials and d.state == filter_state]
    else:
        devices = [d for d in all_devices if d.state == filter_state]

    if filter_model:
        devices = [d for d in devices if d.model == filter_model]
    if max_devices:
        devices = devices[:max_devices]

    if not devices:
        raise ValueError("No READY devices matching filter")

    async with AsyncSessionLocal() as db:
        templates = await list_templates(db)
    registry = _build_scenario_registry([], templates)

    if queue is None:
        raise RuntimeError("No task queue available")

    task_ids: list[str] = []
    _campaign_vars: dict[str, Any] = {}
    _user_id = cfg.get("user_id")
    if _user_id:
        _campaign_vars["__USER_ID__"] = str(_user_id)

    now_bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
    for i, device in enumerate(devices):
        delay = i * stagger_interval if stagger else 0
        payload = {
            "steps": steps,
            "variables": variables,
            "_campaign_vars": _campaign_vars,
            "_scenario_registry": registry,
        }

        # Per-device idempotency. A retried fleet dispatch at the same
        # minute-bucket collapses to one enqueue per device.
        intent_source = (
            f"fleet:{cfg.get('id', 'adhoc')}:dev:{device.serial}:bucket:{now_bucket}"
        )
        try:
            intent = await claim_or_get_intent(
                key=make_idempotency_key(intent_source, payload),
                source=intent_source,
                payload={"serial": device.serial, "bucket": now_bucket},
            )
            if intent.replay and intent.result_ref:
                task_ids.append(intent.result_ref)
                continue
        except Exception as exc:
            log.warning("[fleet] idempotency claim failed for %s: %s", device.serial, exc)
            intent = None

        try:
            task = Task(
                fn=lambda dev: None,
                priority=5,
                target=device.serial,
                timeout=300,
                max_retries=1,
                name=f"schedule:{cfg['id']}:device:{device.serial}",
            )
            task.fn = _make_staggered_task(
                make_scenario_task(payload, cancel_event=task.cancel_event),
                delay_seconds=float(delay),
            )
            queue.put(task)
        except Exception as exc:
            log.error("[fleet] enqueue failed for %s: %s", device.serial, exc)
            if intent is not None:
                try:
                    await mark_intent_failed(intent.id, reason=f"enqueue: {exc}")
                except Exception as mk_exc:
                    log.warning("[fleet] mark_intent_failed failed: %s", mk_exc)
            continue

        task_ids.append(task.id)
        if intent is not None:
            try:
                await mark_intent_accepted(intent.id, result_ref=task.id)
            except Exception as mk_exc:
                log.warning("[fleet] mark_intent_accepted failed: %s", mk_exc)

    return {
        "devices_dispatched": len(devices),
        "task_ids": task_ids,
    }
