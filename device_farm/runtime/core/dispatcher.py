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
from datetime import datetime, timedelta
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
        t.start()

    def _run_task(self, device: DeviceClient, task: Task) -> None:
        serial = device.serial
        log.info(f"[{serial}] Starting task {task.id[:8]} ({task.name or task.fn.__name__})")
        task.started_at = datetime.utcnow()

        result = None
        error_msg = None
        success = False

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
                # Timeout — we can't truly kill the thread in Python,
                # but we mark it as failed and move on.
                error_msg = f"Task timed out after {task.timeout}s"
                log.error(f"[{serial}] {error_msg}")
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
            task.finished_at = datetime.utcnow()
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
            elif scenario_failed or task.retry_count >= task.max_retries:
                task.status = TaskStatus.FAILED
                task.error = error_msg
                log.error(
                    f"[{serial}] Task {task.id[:8]} failed"
                    + (" (scenario steps)" if scenario_failed else " (no retries left)")
                )
            else:
                log.info(
                    f"[{serial}] Task {task.id[:8]} requeuing "
                    f"({task.retry_count + 1}/{task.max_retries})"
                )
                self.queue.requeue(task)

            # Return device to READY if it hasn't been moved to ERROR/DEAD
            if device.state == DeviceState.BUSY:
                device.state = DeviceState.READY

            # NOTE: Campaign status is currently updated explicitly via the API.
            # Dispatcher only manages per-device task lifecycle.

    # ── Rate Limiting ────────────────────────────────────────────────────────

    def _is_rate_limited(self, serial: str) -> bool:
        max_tpm = self.config.dispatcher.max_tasks_per_minute
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=1)

        with self._rate_lock:
            times = self._rate_tracker[serial]
            times[:] = [t for t in times if t > cutoff]
            return len(times) >= max_tpm

    def _record_completion(self, serial: str) -> None:
        with self._rate_lock:
            self._rate_tracker[serial].append(datetime.utcnow())
