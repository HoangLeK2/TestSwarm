"""
dispatcher.py — Dispatcher: assigns tasks from the TaskQueue to idle devices.

Loop every `loop_interval` seconds:
  - For each READY device that is not already running a task:
    - Dequeue the highest-priority matching task
    - Set device → BUSY
    - Execute task.fn(device) in a new daemon thread

On task success: mark DONE
On task exception: requeue if retries remain, else mark FAILED
On timeout: cancel and requeue/fail like an exception
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.device_manager import DeviceManager
from runtime.core.task_queue import Task, TaskQueue, TaskStatus


log = logging.getLogger(__name__)

# Max parallel dispatch checks per cycle — caps CPU usage during large fleet scans
_MAX_DISPATCH_WORKERS = 64


class Dispatcher(threading.Thread):
   

    def __init__(
        self,
        manager: DeviceManager,
        queue: TaskQueue,
        config: Config,
    ) -> None:
        super().__init__(daemon=True, name="dispatcher")
        self.manager = manager
        self.queue = queue
        self.config = config
        self._running = False

        # Rate limiting: track task completion timestamps per device
        self._rate_tracker: Dict[str, List[datetime]] = defaultdict(list)
        self._rate_lock = threading.Lock()

    def start_dispatcher(self) -> None:
        self._running = True
        if not self.is_alive():
            self.start()

    def stop_dispatcher(self) -> None:
        self._running = False

    def run(self) -> None:
        interval = self.config.dispatcher.loop_interval
        log.info(f"Dispatcher started (interval={interval}s)")

        while self._running:
            time.sleep(interval)
            if not self._running:
                break
            self._dispatch_cycle()

    def _dispatch_cycle(self) -> None:
        devices = self.manager.ready_devices()
        if not devices:
            return
        # For small fleets dispatch inline; for large fleets use a thread pool
        # so 1000 devices don't block each other waiting for queue locks.
        if len(devices) <= 8:
            for device in devices:
                self._try_dispatch(device)
        else:
            workers = min(_MAX_DISPATCH_WORKERS, len(devices))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dispatch") as pool:
                pool.map(self._try_dispatch, devices)

    def _try_dispatch(self, device: DeviceClient) -> None:
        if self._is_rate_limited(device.serial):
            return
        # Refuse dispatch if prior worker still alive (zombie from timeout).
        prior = getattr(device, "_active_worker", None)
        if prior is not None and prior.is_alive():
            log.warning(
                f"[{device.serial}] skip dispatch — prior worker still alive "
                f"(thread={prior.name})"
            )
            return
        task = self.queue.get_next(serial=device.serial)
        if task is None:
            return
        device.state = DeviceState.BUSY
        t = threading.Thread(
            target=self._run_task,
            args=(device, task),
            daemon=True,
            name=f"task-{task.id[:8]}-{device.serial}",
        )
        device._active_worker = t
        t.start()

    def _run_task(self, device: DeviceClient, task: Task) -> None:
        serial = device.serial
        log.info(f"[{serial}] Starting task {task.id[:8]} ({task.name or task.fn.__name__})")
        task.started_at = datetime.now(timezone.utc)

        result = None
        error_msg = None
        success = False
        quarantined = False

        try:
          
            try:
                if hasattr(device, "ensure_u2_healthy"):
                    ok = device.ensure_u2_healthy()
                    log.info(
                        f"[{serial}] U2 health‑check before task {task.id[:8]}: "
                        f"{'OK' if ok else 'FAILED'}"
                    )
            except Exception as exc:
                log.warning(f"[{serial}] U2 health‑check error before task {task.id[:8]}: {exc}")

            result_holder: List = [None]
            exc_holder: List = [None]

            def _target():
                try:
                    result_holder[0] = task.fn(device)
                except Exception as exc:
                    exc_holder[0] = exc

            worker = threading.Thread(target=_target, daemon=True)
            worker.start()
            worker.join(timeout=task.timeout)

            if worker.is_alive():
                # Timeout — can't kill Python thread. Signal cooperative cancel
                # (long scenarios poll task.cancel_event) then QUARANTINE device
                # so dispatcher does not assign new task while zombie still running.
                error_msg = f"Task timed out after {task.timeout}s"
                log.error(f"[{serial}] {error_msg} — quarantining device")
                try:
                    task.cancel_event.set()
                except Exception:
                    pass
                # Grace window for cooperative abort
                worker.join(timeout=5.0)
                if worker.is_alive():
                    device._zombie_worker = worker
                    device.state = DeviceState.ERROR
                    quarantined = True
            elif exc_holder[0] is not None:
                raise exc_holder[0]
            else:
                result = result_holder[0]
                success = True
                # Scenario (and similar) tasks can return success=False when steps fail
                if isinstance(result, dict) and result.get("success") is False:
                    success = False
                    error_msg = result.get("failed_message") or "scenario steps failed"

        except Exception as exc:
            error_msg = str(exc)
            log.error(f"[{serial}] Task {task.id[:8]} failed: {exc}", exc_info=True)

        finally:
            task.finished_at = datetime.now(timezone.utc)
            elapsed = (task.finished_at - task.started_at).total_seconds()

            # ── Prometheus metrics (tạm tắt) ──
            # try:
            #     from web.metrics import tasks_dispatched_total, task_duration_seconds
            #     task_duration_seconds.observe(elapsed)
            # except Exception:
            #     pass

            scenario_failed = (
                not success
                and result is not None
                and isinstance(result, dict)
                and result.get("success") is False
            )
            if success:
                task.status = TaskStatus.DONE
                task.result = result
                log.info(f"[{serial}] Task {task.id[:8]} done")
                self._record_completion(serial)
                # try:
                #     from web.metrics import tasks_dispatched_total
                #     tasks_dispatched_total.labels(status="success").inc()
                # except Exception:
                #     pass
            elif scenario_failed or task.retry_count >= task.max_retries:
                task.status = TaskStatus.FAILED
                task.error = error_msg
                log.error(
                    f"[{serial}] Task {task.id[:8]} failed"
                    + (" (scenario steps)" if scenario_failed else " (no retries left)")
                )
                # try:
                #     from web.metrics import tasks_dispatched_total
                #     if error_msg and "timed out" in error_msg:
                #         tasks_dispatched_total.labels(status="timeout").inc()
                #     else:
                #         tasks_dispatched_total.labels(status="failure").inc()
                # except Exception:
                #     pass
            else:
                log.info(
                    f"[{serial}] Task {task.id[:8]} requeuing "
                    f"({task.retry_count + 1}/{task.max_retries})"
                )
                self.queue.requeue(task)

            # Clear active worker pointer if this call's worker finished.
            # If zombie, leave pointer; _try_dispatch will skip device until
            # thread dies or watchdog resets state.
            aw = getattr(device, "_active_worker", None)
            if aw is not None and not aw.is_alive():
                device._active_worker = None

            # Return device to READY if it hasn't been moved to ERROR/DEAD
            # and we did not just quarantine it.
            if not quarantined and device.state == DeviceState.BUSY:
                device.state = DeviceState.READY

            # NOTE: Campaign status is currently updated explicitly via the API.
            # Dispatcher only manages per-device task lifecycle.
            if self.config.database.enabled and task.status in (TaskStatus.DONE, TaskStatus.FAILED):
                try:
                    from services.activity_logger import log_task_activity_sync

                    log_task_activity_sync(task, serial, elapsed)
                except Exception as exc:
                    log.warning("[%s] activity log write skipped for task %s: %s", serial, task.id, exc)

    # ── Rate Limiting ────────────────────────────────────────────────────────

    def _is_rate_limited(self, serial: str) -> bool:
        max_tpm = self.config.dispatcher.max_tasks_per_minute
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=1)

        with self._rate_lock:
            times = self._rate_tracker[serial]
            times[:] = [t for t in times if t > cutoff]
            return len(times) >= max_tpm

    def _record_completion(self, serial: str) -> None:
        with self._rate_lock:
            self._rate_tracker[serial].append(datetime.now(timezone.utc))
