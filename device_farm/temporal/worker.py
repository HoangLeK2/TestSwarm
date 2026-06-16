
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from temporalio.client import Client
from temporalio.worker import Worker

from core.config import TemporalConfig
from temporal.activities import DeviceActivities, set_device_registry, set_temporal_config
from temporal.relay_onboarding_activities import RelayOnboardingActivities
from temporal.relay_onboarding_workflows import RelayOnboardingWorkflow
from temporal.schedule_activities import ScheduleActivities, set_scheduler_deps
from temporal.schedule_workflow import ScheduleRunWorkflow
from temporal.shared import TASK_QUEUE_NAME
from temporal.account_state_activities import AccountStateActivities
from temporal.account_state_workflows import AccountCooldownTickWorkflow
from temporal.trace import TemporalTraceInterceptor
from temporal.workflows import ScenarioWorkflow, ScenarioStepsWorkflow

log = logging.getLogger(__name__)


async def _create_client(cfg: TemporalConfig) -> Client:
    return await Client.connect(
        cfg.server_url,
        namespace=cfg.namespace,
    )


async def create_temporal_worker(
    manager,
    cfg: TemporalConfig,
    client: Optional[Client] = None,
    queue=None,
    worker_index: int = 0,
) -> Worker:
    """
    Create a Temporal worker with all workflows and activities registered.

    worker_index=0 is the primary worker: it registers schedule activities and
    injects scheduler deps. Workers 1..N only register device activities so
    Temporal never routes schedule tasks to a worker with uninitialized deps.
    """
    if client is None:
        client = await _create_client(cfg)

    task_queue = cfg.task_queue or TASK_QUEUE_NAME
    _activities = DeviceActivities()
    _relay_onboarding_activities = RelayOnboardingActivities()

    if worker_index == 0:
        # Primary worker: full activity set including schedule dispatch.
        set_scheduler_deps(queue=queue, manager=manager, temporal_client=client, temporal_config=cfg)
        _schedule_activities = ScheduleActivities()
        _account_state_activities = AccountStateActivities()
        activity_list = [
            _activities.execute_device_action,
            _activities.execute_device_action_batch,
            _activities.check_element_exists,
            _activities.evaluate_condition,
            _activities.evaluate_legacy_condition,
            _activities.execute_extract,
            _activities.execute_save_extraction,
            _activities.finalize_campaign,
            _schedule_activities.load_schedule,
            _schedule_activities.create_run_record,
            _schedule_activities.dispatch_schedule,
            _schedule_activities.finalize_schedule_run,
            _account_state_activities.process_expired_account_cooldowns,
            _relay_onboarding_activities.prepare_relay_onboarding_job,
            _relay_onboarding_activities.run_relay_onboarding_item,
            _relay_onboarding_activities.finish_relay_onboarding_job,
        ]
    else:
        # Secondary workers: device activities only.
        activity_list = [
            _activities.execute_device_action,
            _activities.execute_device_action_batch,
            _activities.check_element_exists,
            _activities.evaluate_condition,
            _activities.evaluate_legacy_condition,
            _activities.execute_extract,
            _activities.execute_save_extraction,
            _activities.finalize_campaign,
            _relay_onboarding_activities.prepare_relay_onboarding_job,
            _relay_onboarding_activities.run_relay_onboarding_item,
            _relay_onboarding_activities.finish_relay_onboarding_job,
        ]

    return Worker(
        client,
        task_queue=task_queue,
        workflows=[
            ScenarioWorkflow,
            ScenarioStepsWorkflow,
            ScheduleRunWorkflow,
            RelayOnboardingWorkflow,
            AccountCooldownTickWorkflow,
        ],
        activities=activity_list,
        interceptors=[TemporalTraceInterceptor()],
        max_concurrent_activities=cfg.worker_max_concurrent_activities,
        max_concurrent_workflow_tasks=cfg.worker_max_concurrent_workflows,
    )


async def _run_worker(
    manager,
    cfg: TemporalConfig,
    queue=None,
    worker_index: int = 0,
) -> None:
    """Run one Temporal worker until shutdown.

    Each call owns its own asyncio event loop (invoked via loop.run_until_complete
    from a dedicated thread) and its own ThreadPoolExecutor.
    """
    tag = f"[worker-{worker_index}]"
    try:
        max_threads = max(cfg.worker_max_concurrent_activities * 2, 20)
        # Use get_running_loop() — unambiguous inside a running coroutine.
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            ThreadPoolExecutor(
                max_workers=max_threads,
                thread_name_prefix=f"device-activity-{worker_index}",
            )
        )
        client = await _create_client(cfg)
        worker = await create_temporal_worker(
            manager, cfg, client, queue=queue, worker_index=worker_index,
        )
        log.info(
            "%s started: server=%s queue=%s activities=%d threads=%d",
            tag, cfg.server_url, cfg.task_queue,
            cfg.worker_max_concurrent_activities, max_threads,
        )
        from temporal.trace import trace_log
        trace_log.info(
            "temporal_worker_started",
            worker_index=worker_index,
            server_url=cfg.server_url,
            task_queue=cfg.task_queue,
            max_concurrent_activities=cfg.worker_max_concurrent_activities,
            max_concurrent_workflows=cfg.worker_max_concurrent_workflows,
            thread_pool_size=max_threads,
        )
        await worker.run()
    except Exception:
        log.exception("%s failed", tag)
        raise


def start_temporal_worker(
    manager,
    cfg: TemporalConfig,
    queue=None,
) -> list[threading.Thread]:
    """Start cfg.worker_count independent Temporal worker threads.

    Globals (device registry, temporal config) are injected once here before
    threads start — avoids write-write races when multiple threads call
    create_temporal_worker concurrently.

    Total activity concurrency = worker_count × max_concurrent_activities.
    """
    # Inject shared globals once, before any thread starts (Issue 2 fix).
    set_device_registry(manager)
    set_temporal_config(cfg)

    worker_count = max(1, cfg.worker_count)
    threads: list[threading.Thread] = []

    for i in range(worker_count):
        def _worker_thread(idx: int = i) -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_run_worker(manager, cfg, queue=queue, worker_index=idx))
            except Exception:
                log.exception("temporal-worker-%d error", idx)
            finally:
                # Dispose the per-loop SQLAlchemy engine before closing the
                # loop so its connection pool releases cleanly. Skipping this
                # leaves asyncpg connections waiting on a dead loop and emits
                # "Task was destroyed" warnings on shutdown.
                try:
                    from db.database import dispose_loop_engine
                    loop.run_until_complete(dispose_loop_engine())
                except Exception as _exc:
                    log.warning("dispose_loop_engine failed on worker %d: %s", idx, _exc)
                loop.close()

        thread = threading.Thread(
            target=_worker_thread,
            daemon=True,
            name=f"temporal-worker-{i}",
        )
        thread.start()
        threads.append(thread)

    log.info(
        "Started %d Temporal worker thread(s): queue=%s activities_per_worker=%d total_slots=%d",
        worker_count, cfg.task_queue,
        cfg.worker_max_concurrent_activities,
        worker_count * cfg.worker_max_concurrent_activities,
    )
    return threads


async def get_temporal_client(cfg: TemporalConfig) -> Client:
    return await _create_client(cfg)
