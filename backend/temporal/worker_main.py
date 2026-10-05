"""
Standalone Temporal worker — runs independently of the FastAPI server.

Use this to scale horizontally: run one farm pod per machine (with its local
devices), all pointing at the same Temporal Server. Temporal distributes
campaign activity tasks across all running workers automatically.

Usage:
    # Single worker process (reads config.yaml)
    python -m temporal.worker_main

    # Override concurrency via env
    TEMPORAL_WORKER_COUNT=4 TEMPORAL_WORKER_MAX_CONCURRENT_ACTIVITIES=30 \\
        python -m temporal.worker_main

Docker / Kubernetes:
    docker run --env-file .env farm-image python -m temporal.worker_main

Scaling formula (one machine):
    total_activity_slots = worker_count × worker_max_concurrent_activities
    thread_pool_per_worker = max(worker_max_concurrent_activities × 2, 20)

    Example — 50 devices on one machine:
        worker_count: 2
        worker_max_concurrent_activities: 30
        → 60 activity slots, 2 pools of 60 threads each
"""
from __future__ import annotations

import logging
import signal
import sys
import threading

from core.config import load_config, setup_logging
from core.env import farm_config_path
from temporal.worker import start_temporal_worker

log = logging.getLogger(__name__)


def main() -> None:
    cfg_path = farm_config_path()
    config = load_config(cfg_path)
    setup_logging(config.logging)

    if not config.temporal.enabled:
        log.error(
            "Temporal is disabled in config (temporal.enabled=false). "
            "Set enabled: true and point server_url at your Temporal server."
        )
        sys.exit(1)

    log.info(
        "Starting standalone Temporal worker: server=%s queue=%s "
        "worker_count=%d max_concurrent_activities=%d",
        config.temporal.server_url,
        config.temporal.task_queue,
        config.temporal.worker_count,
        config.temporal.worker_max_concurrent_activities,
    )

    # Minimal DeviceManager — connects to devices listed in device_index.json.
    # In standalone mode the worker still needs the device registry to resolve
    # get_device(serial) calls from activities.
    from runtime.core.device_manager import DeviceManager
    manager = DeviceManager(config)

    threads = start_temporal_worker(manager, config.temporal, queue=None)

    # Block until SIGINT/SIGTERM — daemon threads stop with the process.
    stop_event = threading.Event()

    def _handle_signal(sig, frame):  # noqa: ANN001
        log.info("Received signal %s — shutting down worker(s)", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info(
        "Worker(s) running (%d thread(s)). Press Ctrl-C or send SIGTERM to stop.",
        len(threads),
    )
    stop_event.wait()
    log.info("Temporal worker process exiting.")


if __name__ == "__main__":
    main()
