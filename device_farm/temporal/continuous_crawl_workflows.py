"""Deterministic orchestration contracts for production continuous crawls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from temporalio import workflow
from temporalio.common import RetryPolicy

from temporal.shared import TASK_QUEUE_NAME, ScenarioInput, StepsResult
from temporal.workflows import ScenarioWorkflow

LOAD_ACTIVITY = "load_continuous_crawl_source_page"
PREPARE_ACTIVITY = "prepare_continuous_crawl_target"
FINALIZE_ACTIVITY = "finalize_continuous_crawl"
CLEANUP_ACTIVITY = "cleanup_continuous_crawl_target"

_IO_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)

MAX_RECENT_TARGETS = 8
PER_DEVICE_BUFFER_SIZE = 8


@dataclass(frozen=True)
class CrawlTarget:
    external_entity_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    device_serial: str | None = None


@dataclass(frozen=True)
class ContinuousCrawlInput:
    campaign_id: str
    dispatch_id: str
    org_id: str
    device_serials: list[str]
    source_pool: dict[str, Any]
    snapshot_at: str
    task_queue: str = TASK_QUEUE_NAME
    max_concurrency: int = 10
    source_page_size: int = 500
    max_targets: int = 100_000
    target_timeout_seconds: int = 600
    maximum_attempts: int = 4
    failure_policy: Literal["continue", "fail_fast"] = "continue"
    max_failure_ratio: float = 0.2
    max_consecutive_failures: int = 20
    cursor: str | None = None
    exhausted: bool = False
    loaded: int = 0
    succeeded: int = 0
    failed: int = 0
    consecutive_failures: int = 0
    generation: int = 0
    continue_after_targets: int = 2_000
    device_lanes: list[dict[str, Any]] = field(default_factory=list)
    recent_targets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class LoadCrawlPageInput:
    campaign_id: str
    dispatch_id: str
    org_id: str
    source_pool: dict[str, Any]
    device_serials: list[str]
    snapshot_at: str
    cursor: str | None
    limit: int


@dataclass(frozen=True)
class LoadCrawlPageResult:
    targets: list[CrawlTarget] = field(default_factory=list)
    next_cursor: str | None = None
    exhausted: bool = False


@dataclass(frozen=True)
class PrepareCrawlTargetInput:
    campaign_id: str
    dispatch_id: str
    org_id: str
    device_serial: str
    target: CrawlTarget
    source_pool: dict[str, Any]


@dataclass(frozen=True)
class PreparedCrawlTarget:
    scenario: ScenarioInput


@dataclass(frozen=True)
class CrawlTargetInput:
    campaign_id: str
    dispatch_id: str
    org_id: str
    device_serial: str
    target: CrawlTarget
    source_pool: dict[str, Any]
    task_queue: str = TASK_QUEUE_NAME
    prepare_timeout_seconds: int = 60


@dataclass(frozen=True)
class CrawlTargetOutcome:
    external_entity_id: str
    device_serial: str
    success: bool
    message: str = ""


@dataclass(frozen=True)
class ContinuousCrawlProgress:
    status: str = "running"
    loaded: int = 0
    active: int = 0
    succeeded: int = 0
    failed: int = 0
    consecutive_failures: int = 0
    cursor: str | None = None
    exhausted: bool = False
    generation: int = 0
    message: str = ""
    device_lanes: list[dict[str, Any]] = field(default_factory=list)
    recent_targets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizeCrawlInput:
    campaign_id: str
    dispatch_id: str
    org_id: str
    status: str
    progress: ContinuousCrawlProgress


@dataclass(frozen=True)
class CleanupCrawlTargetInput:
    campaign_id: str
    dispatch_id: str
    org_id: str
    external_entity_id: str
    device_serial: str
    # Terminal state to settle the execution at when the scenario left it open.
    # Defaulted so histories written before this field existed still decode.
    status: str = "failed"


def circuit_breaker_reason(
    inp: ContinuousCrawlInput, progress: ContinuousCrawlProgress
) -> str | None:
    """Return the deterministic stop reason, if the configured breaker is open."""
    if progress.failed and inp.failure_policy == "fail_fast":
        return "target failed under fail-fast policy"
    if progress.consecutive_failures >= inp.max_consecutive_failures:
        return "maximum consecutive failures exceeded"
    completed = progress.succeeded + progress.failed
    if completed and progress.failed / completed > inp.max_failure_ratio:
        return "maximum failure ratio exceeded"
    return None


@workflow.defn
class ContinuousCrawlTargetWorkflow:
    def __init__(self) -> None:
        self._scenario_child_id: str | None = None

    @workflow.run
    async def run(self, inp: CrawlTargetInput) -> CrawlTargetOutcome:
        try:
            prepared: PreparedCrawlTarget = await workflow.execute_activity(
                PREPARE_ACTIVITY,
                PrepareCrawlTargetInput(
                    campaign_id=inp.campaign_id,
                    dispatch_id=inp.dispatch_id,
                    org_id=inp.org_id,
                    device_serial=inp.device_serial,
                    target=inp.target,
                    source_pool=inp.source_pool,
                ),
                result_type=PreparedCrawlTarget,
                start_to_close_timeout=timedelta(seconds=inp.prepare_timeout_seconds),
                retry_policy=_IO_RETRY,
            )
            self._scenario_child_id = f"{workflow.info().workflow_id}:scenario"
            result: StepsResult = await workflow.execute_child_workflow(
                ScenarioWorkflow.run,
                prepared.scenario,
                id=self._scenario_child_id,
                task_queue=inp.task_queue,
            )
            return CrawlTargetOutcome(
                external_entity_id=inp.target.external_entity_id,
                device_serial=inp.device_serial,
                success=result.success,
                message=result.failed_message or "",
            )
        except Exception as exc:  # noqa: BLE001 - child/activity failures are outcomes
            return CrawlTargetOutcome(
                external_entity_id=inp.target.external_entity_id,
                device_serial=inp.device_serial,
                success=False,
                message=str(exc),
            )

    async def _forward(self, signal: str) -> None:
        if self._scenario_child_id is None:
            return
        try:
            await workflow.get_external_workflow_handle(self._scenario_child_id).signal(
                signal
            )
        except Exception:  # noqa: BLE001, S110
            # The child may already be closed when a control signal arrives.
            pass

    @workflow.signal
    async def pause(self) -> None:
        await self._forward("pause")

    @workflow.signal
    async def resume(self) -> None:
        await self._forward("resume")

    @workflow.signal
    async def cancel(self) -> None:
        await self._forward("cancel_scenario")


@workflow.defn
class ContinuousCrawlWorkflow:
    def __init__(self) -> None:
        self._paused = False
        self._cancelled = False
        self._progress = ContinuousCrawlProgress()
        self._active_child_ids: set[str] = set()

    @workflow.run
    async def run(self, inp: ContinuousCrawlInput) -> ContinuousCrawlProgress:
        if not inp.device_serials:
            raise ValueError("continuous crawl requires at least one device")
        lane_count = min(inp.max_concurrency, len(inp.device_serials))
        queues: dict[str, asyncio.Queue[CrawlTarget | None]] = {
            serial: asyncio.Queue(maxsize=PER_DEVICE_BUFFER_SIZE)
            for serial in inp.device_serials[:lane_count]
        }
        self._progress = ContinuousCrawlProgress(
            loaded=inp.loaded,
            succeeded=inp.succeeded,
            failed=inp.failed,
            consecutive_failures=inp.consecutive_failures,
            cursor=inp.cursor,
            exhausted=inp.exhausted,
            generation=inp.generation,
        )
        self._initialize_operational_progress(inp, lane_count)
        lanes = [
            asyncio.create_task(self._run_lane(inp, serial, queues[serial]))
            for serial in inp.device_serials[:lane_count]
        ]
        cursor, exhausted = inp.cursor, inp.exhausted
        loaded_this_run = 0
        try:
            while not exhausted and self._progress.loaded < inp.max_targets:
                await workflow.wait_condition(
                    lambda: not self._paused or self._cancelled
                )
                if self._cancelled or circuit_breaker_reason(inp, self._progress):
                    break
                limit = min(
                    inp.source_page_size, inp.max_targets - self._progress.loaded
                )
                page: LoadCrawlPageResult = await workflow.execute_activity(
                    LOAD_ACTIVITY,
                    LoadCrawlPageInput(
                        campaign_id=inp.campaign_id,
                        dispatch_id=inp.dispatch_id,
                        org_id=inp.org_id,
                        source_pool=inp.source_pool,
                        device_serials=inp.device_serials[:lane_count],
                        snapshot_at=inp.snapshot_at,
                        cursor=cursor,
                        limit=limit,
                    ),
                    result_type=LoadCrawlPageResult,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=_IO_RETRY,
                )
                targets = page.targets[:limit]
                for target in targets:
                    device_serial = str(target.device_serial or "")
                    if device_serial not in queues:
                        raise ValueError(
                            "assigned crawl target references an unknown device"
                        )
                await asyncio.gather(
                    *(
                        queues[str(target.device_serial)].put(target)
                        for target in targets
                    )
                )
                loaded_this_run += len(targets)
                self._replace_progress(loaded=self._progress.loaded + len(targets))
                cursor, exhausted = page.next_cursor, page.exhausted
                self._replace_progress(cursor=cursor, exhausted=exhausted)
                if loaded_this_run >= inp.continue_after_targets:
                    break
        finally:
            for queue in queues.values():
                await queue.put(None)
            await asyncio.gather(*lanes)

        reason = circuit_breaker_reason(inp, self._progress)
        if (
            not self._cancelled
            and reason is None
            and not exhausted
            and self._progress.loaded < inp.max_targets
        ):
            await workflow.continue_as_new(
                ContinuousCrawlInput(
                    **{
                        **inp.__dict__,
                        "cursor": cursor,
                        "exhausted": exhausted,
                        "loaded": self._progress.loaded,
                        "succeeded": self._progress.succeeded,
                        "failed": self._progress.failed,
                        "consecutive_failures": self._progress.consecutive_failures,
                        "generation": inp.generation + 1,
                        "device_lanes": self._progress.device_lanes,
                        "recent_targets": self._progress.recent_targets,
                    }
                )
            )

        status = "cancelled" if self._cancelled else "failed" if reason else "completed"
        self._replace_progress(status=status, message=reason or "")
        await workflow.execute_activity(
            FINALIZE_ACTIVITY,
            FinalizeCrawlInput(
                inp.campaign_id, inp.dispatch_id, inp.org_id, status, self._progress
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_IO_RETRY,
        )
        return self._progress

    async def _run_lane(
        self,
        inp: ContinuousCrawlInput,
        device_serial: str,
        queue: asyncio.Queue[CrawlTarget | None],
    ) -> None:
        while True:
            target = await queue.get()
            if target is None:
                return
            await workflow.wait_condition(lambda: not self._paused or self._cancelled)
            if self._cancelled or circuit_breaker_reason(inp, self._progress):
                continue
            child_id = (
                f"{workflow.info().workflow_id}:device:{device_serial}:"
                f"target:{target.external_entity_id}"
            )
            self._active_child_ids.add(child_id)
            self._replace_progress(active=len(self._active_child_ids))
            self._mark_target_running(device_serial, target)
            try:
                outcome: CrawlTargetOutcome = await workflow.execute_child_workflow(
                    ContinuousCrawlTargetWorkflow.run,
                    CrawlTargetInput(
                        inp.campaign_id,
                        inp.dispatch_id,
                        inp.org_id,
                        device_serial,
                        target,
                        inp.source_pool,
                        inp.task_queue,
                    ),
                    id=child_id,
                    task_queue=inp.task_queue,
                    execution_timeout=timedelta(seconds=inp.target_timeout_seconds),
                    retry_policy=RetryPolicy(maximum_attempts=inp.maximum_attempts),
                )
                if outcome.success:
                    # A succeeded target still gets settled. Releasing the phone
                    # is the scenario's job (ScenarioWorkflow._finalize), but
                    # that runs on the control queue and can be dropped without
                    # the target hearing about it — and then the claim sits on
                    # the device for the full 1800s campaign TTL with nothing
                    # running. This is a no-op whenever the execution is already
                    # terminal, which is the normal case.
                    cleanup_error = await self._cleanup_target(
                        inp, device_serial, target, status="completed"
                    )
                    self._replace_progress(
                        succeeded=self._progress.succeeded + 1,
                        consecutive_failures=0,
                    )
                    message = self._failure_message(outcome.message, cleanup_error)
                else:
                    cleanup_error = await self._cleanup_failed_target(
                        inp, device_serial, target
                    )
                    self._record_failure()
                    message = self._failure_message(outcome.message, cleanup_error)
                self._mark_target_finished(
                    device_serial,
                    target,
                    success=outcome.success,
                    message=message,
                )
            except Exception as exc:  # noqa: BLE001 - keep other device lanes alive
                cleanup_error = await self._cleanup_failed_target(
                    inp, device_serial, target
                )
                self._record_failure()
                self._mark_target_finished(
                    device_serial,
                    target,
                    success=False,
                    message=self._failure_message(str(exc), cleanup_error),
                )
            finally:
                self._active_child_ids.discard(child_id)
                active = len(self._active_child_ids)
                self._replace_progress(
                    active=active,
                    status="paused"
                    if self._paused and active == 0
                    else self._progress.status,
                )

    async def _cleanup_failed_target(
        self,
        inp: ContinuousCrawlInput,
        device_serial: str,
        target: CrawlTarget,
    ) -> str:
        return await self._cleanup_target(
            inp, device_serial, target, status="failed"
        )

    async def _cleanup_target(
        self,
        inp: ContinuousCrawlInput,
        device_serial: str,
        target: CrawlTarget,
        *,
        status: str,
    ) -> str:
        try:
            await workflow.execute_activity(
                CLEANUP_ACTIVITY,
                CleanupCrawlTargetInput(
                    inp.campaign_id,
                    inp.dispatch_id,
                    inp.org_id,
                    target.external_entity_id,
                    device_serial,
                    status,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_IO_RETRY,
            )
        except Exception as exc:  # noqa: BLE001 - cleanup failure is reported upstream
            return str(exc)
        return ""

    @staticmethod
    def _failure_message(message: str, cleanup_error: str) -> str:
        if not cleanup_error:
            return message
        detail = f"cleanup failed: {cleanup_error}"
        return f"{message}; {detail}" if message else detail

    def _record_failure(self) -> None:
        self._replace_progress(
            failed=self._progress.failed + 1,
            consecutive_failures=self._progress.consecutive_failures + 1,
        )

    def _initialize_operational_progress(
        self,
        inp: ContinuousCrawlInput,
        lane_count: int,
    ) -> None:
        previous = {
            str(lane.get("device_serial")): lane
            for lane in inp.device_lanes
            if isinstance(lane, dict) and lane.get("device_serial")
        }
        lanes: list[dict[str, Any]] = []
        for serial in inp.device_serials[:lane_count]:
            carried = previous.get(serial, {})
            lanes.append(
                {
                    "device_serial": serial,
                    "status": "idle",
                    "target_id": None,
                    "target_label": None,
                    "completed": int(carried.get("completed") or 0),
                    "failed": int(carried.get("failed") or 0),
                    "message": None,
                }
            )
        self._replace_progress(
            device_lanes=lanes,
            recent_targets=[
                dict(target)
                for target in inp.recent_targets[:MAX_RECENT_TARGETS]
                if isinstance(target, dict)
            ],
        )

    @staticmethod
    def _target_label(target: CrawlTarget) -> str | None:
        label = target.payload.get("display_name") or target.payload.get("name")
        return str(label) if label else None

    def _mark_target_running(
        self,
        device_serial: str,
        target: CrawlTarget,
    ) -> None:
        self._update_lane(
            device_serial,
            status="running",
            target_id=target.external_entity_id,
            target_label=self._target_label(target),
            message=None,
        )
        self._upsert_recent_target(
            target,
            device_serial=device_serial,
            status="running",
            message=None,
        )

    def _mark_target_finished(
        self,
        device_serial: str,
        target: CrawlTarget,
        *,
        success: bool,
        message: str,
    ) -> None:
        self._update_lane(
            device_serial,
            status="idle",
            target_id=None,
            target_label=None,
            completed_delta=1 if success else 0,
            failed_delta=0 if success else 1,
            message=None if success else message or None,
        )
        self._upsert_recent_target(
            target,
            device_serial=device_serial,
            status="succeeded" if success else "failed",
            message=message or None,
        )

    def _update_lane(
        self,
        device_serial: str,
        *,
        status: str,
        target_id: str | None,
        target_label: str | None,
        completed_delta: int = 0,
        failed_delta: int = 0,
        message: str | None,
    ) -> None:
        lanes: list[dict[str, Any]] = []
        for lane in self._progress.device_lanes:
            if lane.get("device_serial") != device_serial:
                lanes.append(lane)
                continue
            lanes.append(
                {
                    **lane,
                    "status": status,
                    "target_id": target_id,
                    "target_label": target_label,
                    "completed": int(lane.get("completed") or 0) + completed_delta,
                    "failed": int(lane.get("failed") or 0) + failed_delta,
                    "message": message,
                }
            )
        self._replace_progress(device_lanes=lanes)

    def _upsert_recent_target(
        self,
        target: CrawlTarget,
        *,
        device_serial: str,
        status: str,
        message: str | None,
    ) -> None:
        summary = {
            "target_id": target.external_entity_id,
            "label": self._target_label(target),
            "status": status,
            "device_serial": device_serial,
            "message": message,
        }
        rows = [
            row
            for row in self._progress.recent_targets
            if not (
                row.get("target_id") == target.external_entity_id
                and row.get("device_serial") == device_serial
            )
        ]
        self._replace_progress(recent_targets=[summary, *rows][:MAX_RECENT_TARGETS])

    def _replace_progress(self, **changes: Any) -> None:
        self._progress = ContinuousCrawlProgress(
            **{**self._progress.__dict__, **changes}
        )

    async def _signal_children(self, signal: str) -> None:
        for child_id in sorted(self._active_child_ids):
            try:
                await workflow.get_external_workflow_handle(child_id).signal(signal)
            except Exception:  # noqa: BLE001, S110
                # A completed child no longer needs the forwarded signal.
                pass

    @workflow.signal
    async def pause(self) -> None:
        # Deliberately does NOT forward to children, unlike resume: pause drains.
        # The lane stops accepting new targets and the target already on a phone
        # is allowed to finish, which is what the confirm dialog promises and
        # what the pausing → paused status transition in _run_lane reports.
        # Interrupting a scenario mid-run is `cancel`.
        # Guarded by test_pause_drains_active_targets_without_forwarding_pause.
        self._paused = True
        self._replace_progress(status="pausing" if self._active_child_ids else "paused")

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False
        self._replace_progress(status="running")
        await self._signal_children("resume")

    @workflow.signal
    async def cancel(self) -> None:
        self._cancelled = True
        self._replace_progress(status="cancelling")
        await self._signal_children("cancel")

    @workflow.query
    def get_progress(self) -> ContinuousCrawlProgress:
        return self._progress
