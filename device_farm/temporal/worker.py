
from __future__ import annotations

import asyncio
import logging
import threading
import weakref
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
from temporal.shared import CONTROL_TASK_QUEUE_NAME, TASK_QUEUE_NAME
from temporal.account_state_activities import AccountStateActivities
from temporal.account_state_workflows import AccountCooldownTickWorkflow
from temporal.capacity_probe import capacity_probe, db_hold_probe
from temporal.capacity_probe_workflows import CapacityProbeWorkflow, DbHoldProbeWorkflow
from temporal.continuous_crawl_workflows import (
    ContinuousCrawlTargetWorkflow,
    ContinuousCrawlWorkflow,
)
from temporal.continuous_crawl_activities import (
    cleanup_continuous_crawl_target,
    finalize_continuous_crawl,
    load_continuous_crawl_source_page,
    prepare_continuous_crawl_target,
)
from temporal.trace import TemporalTraceInterceptor
from temporal.workflows import ScenarioWorkflow, ScenarioStepsWorkflow

log = logging.getLogger(__name__)

# Temporal workflow sandbox validation imports modules under a process-wide
# import lock. Creating multiple Workers concurrently (worker_count>1) can
# deadlock on first import of temporal.workflows / schedule_workflow.
_worker_init_lock = threading.Lock()

# Temporal clients cached per (event loop, server, namespace) — see
# get_temporal_client for why this is not a single global.
_loop_clients: dict[tuple[int, str, str], tuple["weakref.ref", Client]] = {}
_loop_client_locks: dict[int, asyncio.Lock] = {}
_loop_clients_lock = threading.Lock()


async def _create_client(cfg: TemporalConfig) -> Client:
    return await Client.connect(
        cfg.server_url,
        namespace=cfg.namespace,
    )


ROLE_DEVICE = "device"
ROLE_CONTROL = "control"


async def create_temporal_worker(
    manager,
    cfg: TemporalConfig,
    client: Optional[Client] = None,
    queue=None,
    worker_index: int = 0,
    role: str = ROLE_DEVICE,
) -> Worker:
    """
    Create a Temporal worker with all workflows and activities registered.

    Two roles, split by how long an activity runs rather than by feature:

    - ``device`` polls cfg.task_queue and runs the long, phone-bound work. It
      still registers the control activities too, so a workflow dispatching them
      to the old queue keeps working while a queue migration is in flight.
    - ``control`` polls cfg.control_task_queue and runs only the short
      activities. They are the ones that must never wait: measured on the shared
      queue, a 34ms activity took 20.5s to start once 140 slots were busy, and
      finalize_campaign — which releases the phone — is one of them.

    Workflows are registered on device workers only. Workflow tasks draw on a
    separate slot pool and were never the thing being starved, so splitting them
    would add moving parts for nothing.

    Among device workers, worker_index=0 is still the only one registering
    schedule activities, so Temporal never routes a schedule task to a worker
    with uninitialized deps.
    """
    if client is None:
        client = await _create_client(cfg)

    _activities = DeviceActivities()
    _relay_onboarding_activities = RelayOnboardingActivities()
    _account_state_activities = AccountStateActivities()

    # Short, control-plane work. Kept as one list so the device role and the
    # control role cannot drift apart during the migration.
    #
    # Registration here is deliberately wider than routing: only the frequent
    # ones (finalize_campaign, the claim heartbeat, the cooldown tick, the short
    # schedule steps) are dispatched to the control queue today. The onboarding
    # and crawl bookkeeping activities are registered but still dispatched to
    # the device queue — they are rare and carry minute-scale timeouts, so
    # routing them now would add migration risk for no measured gain. They can
    # be routed later without touching worker registration.
    control_activities = [
        _activities.heartbeat_campaign_device_claim,
        _activities.finalize_campaign,
        _activities.persist_step_checkpoint,
        _activities.emit_control_flow_event,
        _activities.emit_temporal_activity_event,
        _account_state_activities.process_expired_account_cooldowns,
        prepare_continuous_crawl_target,
        finalize_continuous_crawl,
        cleanup_continuous_crawl_target,
        _relay_onboarding_activities.prepare_relay_onboarding_job,
        _relay_onboarding_activities.finish_relay_onboarding_job,
    ]
    # Long, device-bound work.
    device_activities = [
        _activities.execute_device_action,
        _activities.execute_device_action_batch,
        _activities.check_element_exists,
        _activities.evaluate_condition,
        _activities.evaluate_legacy_condition,
        _activities.execute_extract,
        _activities.execute_save_extraction,
        _relay_onboarding_activities.run_relay_onboarding_item,
        load_continuous_crawl_source_page,
        capacity_probe,
        db_hold_probe,
    ]

    if role == ROLE_CONTROL:
        # Deliberately no set_scheduler_deps here. Those globals hold a Temporal
        # client, and this worker's client is bound to this worker's event loop —
        # injecting it would hand dispatch_schedule (which runs on device worker
        # 0's loop) a client from a different loop. Schedule activities are not
        # dispatched to this queue, so the deps are not needed either.
        task_queue = cfg.control_task_queue or CONTROL_TASK_QUEUE_NAME
        workflows: list = []
        activity_list = [
            *control_activities,
            # Probes run here too so a capacity test can target either queue.
            capacity_probe,
            db_hold_probe,
        ]
        max_activities = cfg.control_worker_max_concurrent_activities
    else:
        task_queue = cfg.task_queue or TASK_QUEUE_NAME
        workflows = [
            ScenarioWorkflow,
            ScenarioStepsWorkflow,
            ScheduleRunWorkflow,
            RelayOnboardingWorkflow,
            AccountCooldownTickWorkflow,
            CapacityProbeWorkflow,
            DbHoldProbeWorkflow,
            ContinuousCrawlWorkflow,
            ContinuousCrawlTargetWorkflow,
        ]
        activity_list = [*device_activities, *control_activities]
        if worker_index == 0:
            set_scheduler_deps(
                queue=queue, manager=manager, temporal_client=client, temporal_config=cfg
            )
            _schedule_activities = ScheduleActivities()
            activity_list += [
                _schedule_activities.load_schedule,
                _schedule_activities.create_run_record,
                _schedule_activities.dispatch_schedule,
                _schedule_activities.finalize_schedule_run,
            ]
        max_activities = cfg.worker_max_concurrent_activities

    with _worker_init_lock:
        return Worker(
            client,
            task_queue=task_queue,
            workflows=workflows,
            activities=activity_list,
            interceptors=[TemporalTraceInterceptor()],
            max_concurrent_activities=max_activities,
            max_concurrent_workflow_tasks=cfg.worker_max_concurrent_workflows,
            # Explicit: the SDK default of 1000 is per worker, and this process
            # runs cfg.worker_count of them in one address space.
            max_cached_workflows=cfg.worker_max_cached_workflows,
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


def _ensure_manager_event_loop(manager, loop) -> None:
    """Give the device registry a loop when nothing else has.

    ``temporal.worker_main`` builds a bare DeviceManager and never runs the web
    lifespan, so ``register_event_loop`` is never called and every DeviceClient
    is left with ``_loop = None``. Anything that hands work to the loop then
    no-ops silently — including the Redis publish of ``scenario_active``, which
    is the only way the web process learns the phone is busy. Without it,
    /api/devices/live reports an idle device for the whole run.

    In-process mode (web lifespan → start_temporal_worker) already registered
    the app loop; leave that one alone.
    """
    if getattr(manager, "_event_loop", None) is not None:
        return
    register = getattr(manager, "register_event_loop", None)
    if register is None:
        return
    try:
        register(loop)
        log.info("Registered worker event loop on the device registry")
    except Exception as exc:
        log.warning("Could not register worker event loop: %s", exc)


def start_temporal_worker(
    manager,
    cfg: TemporalConfig,
    queue=None,
) -> list[threading.Thread]:
    """Start cfg.worker_count independent Temporal worker threads.

    Globals (device registry, temporal config) are injected once here before
    threads start — avoids write-write races when multiple threads call
    create_temporal_worker concurrently.

    Workers are started sequentially: thread N only begins after worker N-1
    has finished sandbox validation. Concurrent Worker() construction deadlocks
    on CPython's import locks inside Temporal's workflow sandbox.

    Total activity concurrency = worker_count × max_concurrent_activities.
    """
    # Inject shared globals once, before any thread starts (Issue 2 fix).
    set_device_registry(manager)
    set_temporal_config(cfg)

    threads: list[threading.Thread] = []

    def _start_one(idx: int, role: str, task_queue: str, max_activities: int) -> None:
        ready = threading.Event()
        failed = threading.Event()
        name = f"temporal-{role}-worker-{idx}"

        def _worker_thread(
            idx: int = idx,
            role: str = role,
            task_queue: str = task_queue,
            max_activities: int = max_activities,
            ready_evt: threading.Event = ready,
            failed_evt: threading.Event = failed,
        ) -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _run_and_signal() -> None:
                try:
                    max_threads = max(max_activities * 2, 20)
                    loop_ref = asyncio.get_running_loop()
                    loop_ref.set_default_executor(
                        ThreadPoolExecutor(
                            max_workers=max_threads,
                            thread_name_prefix=f"{role}-activity-{idx}",
                        )
                    )
                    _ensure_manager_event_loop(manager, loop_ref)
                    client = await _create_client(cfg)
                    worker = await create_temporal_worker(
                        manager, cfg, client, queue=queue, worker_index=idx, role=role,
                    )
                    ready_evt.set()
                    from temporal.trace import trace_log
                    trace_log.info(
                        "temporal_worker_started",
                        worker_index=idx,
                        worker_role=role,
                        server_url=cfg.server_url,
                        task_queue=task_queue,
                        max_concurrent_activities=max_activities,
                        max_concurrent_workflows=cfg.worker_max_concurrent_workflows,
                        thread_pool_size=max_threads,
                    )
                    log.info(
                        "[%s-worker-%d] started: server=%s queue=%s activities=%d threads=%d",
                        role, idx, cfg.server_url, task_queue, max_activities, max_threads,
                    )
                    await worker.run()
                except Exception:
                    failed_evt.set()
                    ready_evt.set()
                    raise

            try:
                loop.run_until_complete(_run_and_signal())
            except Exception:
                log.exception("%s error", name)
            finally:
                try:
                    from db.database import dispose_loop_engine
                    loop.run_until_complete(dispose_loop_engine())
                except Exception as _exc:
                    log.warning("dispose_loop_engine failed on %s: %s", name, _exc)
                try:
                    loop.run_until_complete(dispose_loop_clients())
                except Exception as _exc:
                    log.warning("dispose_loop_clients failed on %s: %s", name, _exc)
                loop.close()

        thread = threading.Thread(target=_worker_thread, daemon=True, name=name)
        thread.start()
        if not ready.wait(timeout=120):
            raise RuntimeError(f"{name} did not become ready within 120s")
        if failed.is_set():
            raise RuntimeError(f"{name} failed during startup")
        threads.append(thread)

    worker_count = max(1, cfg.worker_count)
    for i in range(worker_count):
        _start_one(
            i,
            ROLE_DEVICE,
            cfg.task_queue or TASK_QUEUE_NAME,
            cfg.worker_max_concurrent_activities,
        )
    for i in range(max(0, cfg.control_worker_count)):
        _start_one(
            i,
            ROLE_CONTROL,
            cfg.control_task_queue or CONTROL_TASK_QUEUE_NAME,
            cfg.control_worker_max_concurrent_activities,
        )

    control_count = max(0, cfg.control_worker_count)
    log.info(
        "Started Temporal workers: %d device on %s (%d slots each, %d total) + "
        "%d control on %s (%d slots each, %d total)",
        worker_count, cfg.task_queue,
        cfg.worker_max_concurrent_activities,
        worker_count * cfg.worker_max_concurrent_activities,
        control_count, cfg.control_task_queue,
        cfg.control_worker_max_concurrent_activities,
        control_count * cfg.control_worker_max_concurrent_activities,
    )
    return threads


async def get_temporal_client(cfg: TemporalConfig) -> Client:
    """Return the Temporal client shared by everything on this event loop.

    This used to open a fresh gRPC channel on every call, from 19 call sites —
    several of them hot API routes. Measured: 200 clients cost +200 file
    descriptors and +14MB RSS, and each connect is 1-4ms that buys nothing.

    Cached per event loop rather than in one global: each worker thread runs its
    own loop and FastAPI runs another. This mirrors ``_engine_for_loop`` in
    db/database.py. Sharing is safe because nothing in the codebase closes a
    client — web/server.py already keeps one alive on ``app.state`` for the
    process lifetime.
    """
    loop = asyncio.get_running_loop()
    key = (id(loop), cfg.server_url, cfg.namespace)

    # The entry holds a weakref to the loop it was built for. id() is reused
    # once a loop is collected, so keying on it alone would hand a fresh loop a
    # client bound to a dead one; comparing the weakref makes a stale id a miss.
    entry = _loop_clients.get(key)
    if entry is not None and entry[0]() is loop:
        return entry[1]

    # Per-loop asyncio lock: a threading.Lock held across the connect await
    # would block every other coroutine on this loop.
    with _loop_clients_lock:
        lock = _loop_client_locks.get(id(loop))
        if lock is None:
            lock = asyncio.Lock()
            _loop_client_locks[id(loop)] = lock

    async with lock:
        entry = _loop_clients.get(key)
        if entry is not None and entry[0]() is loop:
            return entry[1]
        client = await _create_client(cfg)
        _loop_clients[key] = (weakref.ref(loop), client)
        return client


async def dispose_loop_clients() -> None:
    """Drop this loop's cached clients. Call on loop shutdown.

    Without this, a closed loop's entry would linger and a later loop reusing
    the same id() would inherit a client bound to a dead loop.
    """
    loop_id = id(asyncio.get_running_loop())
    with _loop_clients_lock:
        for key in [k for k in _loop_clients if k[0] == loop_id]:
            _loop_clients.pop(key, None)
        _loop_client_locks.pop(loop_id, None)
