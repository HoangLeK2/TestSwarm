
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from temporalio.client import Client
from temporalio.worker import Worker

from core.config import TemporalConfig
from temporal.activities import DeviceActivities, set_device_registry
from temporal.schedule_activities import ScheduleActivities, set_scheduler_deps
from temporal.schedule_workflow import ScheduleRunWorkflow
from temporal.shared import TASK_QUEUE_NAME
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
) -> Worker:
    """
    Create a Temporal worker with all workflows and activities registered.

    Args:
        manager: DeviceManager instance (provides get_device())
        cfg: TemporalConfig from config.yaml
        client: Optional pre-created Temporal client
        queue: TaskQueue instance (for ScheduleActivities fallback dispatch)
    """
    # Inject device registry into device activities
    set_device_registry(manager)
    # Inject runtime deps into schedule activities
    set_scheduler_deps(queue=queue, manager=manager, temporal_client=client, temporal_config=cfg)

    if client is None:
        client = await _create_client(cfg)
        # Re-inject client now that it's created
        set_scheduler_deps(queue=queue, manager=manager, temporal_client=client, temporal_config=cfg)

    task_queue = cfg.task_queue or TASK_QUEUE_NAME

    _activities = DeviceActivities()
    _schedule_activities = ScheduleActivities()
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[ScenarioWorkflow, ScenarioStepsWorkflow, ScheduleRunWorkflow],
        activities=[
            _activities.execute_device_action,
            _activities.check_element_exists,
            _activities.evaluate_condition,
            _schedule_activities.load_schedule,
            _schedule_activities.create_run_record,
            _schedule_activities.dispatch_schedule,
            _schedule_activities.finalize_schedule_run,
        ],
        max_concurrent_activities=cfg.worker_max_concurrent_activities,
        max_concurrent_workflow_tasks=cfg.worker_max_concurrent_workflows,
    )

    return worker


async def _run_worker(manager, cfg: TemporalConfig, queue=None) -> None:
    """Run the Temporal worker until shutdown."""
    try:
        client = await _create_client(cfg)
        worker = await create_temporal_worker(manager, cfg, client, queue=queue)
        log.info(
            "Temporal worker started: server=%s queue=%s namespace=%s",
            cfg.server_url, cfg.task_queue, cfg.namespace,
        )
        await worker.run()
    except Exception:
        log.exception("Temporal worker failed")
        raise


def start_temporal_worker(
    manager,
    cfg: TemporalConfig,
    queue=None,
) -> threading.Thread:

    def _worker_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_worker(manager, cfg, queue=queue))
        except Exception:
            log.exception("Temporal worker thread error")
        finally:
            loop.close()

    thread = threading.Thread(
        target=_worker_thread,
        daemon=True,
        name="temporal-worker",
    )
    thread.start()
    return thread


async def get_temporal_client(cfg: TemporalConfig) -> Client:
    return await _create_client(cfg)
