from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from relay.adb_admission import (
    AdbAdmissionController,
    AdbLane,
    classify_adb_command,
)


def test_one_phone_is_serialized_without_blocking_another_phone() -> None:
    controller = AdbAdmissionController(
        max_concurrency=3,
        reserved_interactive=1,
        max_heavy=2,
    )
    active_by_serial: dict[str, int] = {}
    max_by_serial: dict[str, int] = {}
    phone_b_started = threading.Event()
    lock = threading.Lock()

    def operation(serial: str, delay_s: float) -> None:
        with controller.admit(serial=serial, lane=AdbLane.DEFAULT):
            with lock:
                active_by_serial[serial] = active_by_serial.get(serial, 0) + 1
                max_by_serial[serial] = max(
                    max_by_serial.get(serial, 0),
                    active_by_serial[serial],
                )
            if serial == "phone-b":
                phone_b_started.set()
            time.sleep(delay_s)
            with lock:
                active_by_serial[serial] -= 1

    with ThreadPoolExecutor(max_workers=3) as pool:
        first_a = pool.submit(operation, "phone-a", 0.08)
        second_a = pool.submit(operation, "phone-a", 0.01)
        phone_b = pool.submit(operation, "phone-b", 0.01)

        assert phone_b_started.wait(timeout=0.05)
        first_a.result(timeout=1)
        second_a.result(timeout=1)
        phone_b.result(timeout=1)

    assert max_by_serial == {"phone-a": 1, "phone-b": 1}


def test_interactive_work_uses_reserved_capacity_ahead_of_maintenance() -> None:
    controller = AdbAdmissionController(
        max_concurrency=2,
        reserved_interactive=1,
        max_heavy=2,
    )
    active_started = threading.Barrier(3)
    release_first = threading.Event()
    release_rest = threading.Event()
    queued_maintenance_started = threading.Event()
    interactive_started = threading.Event()

    def active_maintenance(serial: str, release: threading.Event) -> None:
        with controller.admit(serial=serial, lane=AdbLane.MAINTENANCE):
            active_started.wait(timeout=1)
            release.wait(timeout=1)

    def queued_maintenance() -> None:
        with controller.admit(serial="phone-c", lane=AdbLane.MAINTENANCE):
            queued_maintenance_started.set()

    def interactive() -> None:
        with controller.admit(serial="phone-d", lane=AdbLane.INTERACTIVE):
            interactive_started.set()

    with ThreadPoolExecutor(max_workers=4) as pool:
        active = [
            pool.submit(active_maintenance, "phone-a", release_first),
            pool.submit(active_maintenance, "phone-b", release_rest),
        ]
        active_started.wait(timeout=1)
        setup = pool.submit(queued_maintenance)
        control = pool.submit(interactive)

        deadline = time.monotonic() + 0.2
        while controller.snapshot()["waiting"] < 2 and time.monotonic() < deadline:
            time.sleep(0.001)

        release_first.set()
        assert interactive_started.wait(timeout=0.2)
        assert not queued_maintenance_started.is_set()
        release_rest.set()
        for future in [*active, setup]:
            future.result(timeout=1)
        control.result(timeout=1)

    assert queued_maintenance_started.is_set()


def test_same_phone_waiters_keep_enqueue_order_across_lanes() -> None:
    controller = AdbAdmissionController(
        max_concurrency=1,
        reserved_interactive=0,
        max_heavy=1,
    )
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    order: list[str] = []

    def blocker() -> None:
        with controller.admit(serial="phone-blocker", lane=AdbLane.DEFAULT):
            blocker_started.set()
            release_blocker.wait(timeout=1)

    def queued(label: str, lane: AdbLane) -> None:
        with controller.admit(serial="phone-shared", lane=lane):
            order.append(label)

    with ThreadPoolExecutor(max_workers=3) as pool:
        active = pool.submit(blocker)
        assert blocker_started.wait(timeout=0.2)
        maintenance = pool.submit(queued, "maintenance", AdbLane.MAINTENANCE)
        interactive = pool.submit(queued, "interactive", AdbLane.INTERACTIVE)
        release_blocker.set()
        active.result(timeout=1)
        maintenance.result(timeout=1)
        interactive.result(timeout=1)

    assert order == ["maintenance", "interactive"]


def test_waiting_maintenance_makes_progress_under_interactive_load() -> None:
    controller = AdbAdmissionController(
        max_concurrency=3,
        reserved_interactive=1,
        max_heavy=2,
    )
    interactive_started = threading.Barrier(4)
    release_first = threading.Event()
    release_rest = threading.Event()
    maintenance_started = threading.Event()
    release_maintenance = threading.Event()

    def interactive(
        serial: str,
        release: threading.Event,
        *,
        announce: bool = False,
    ) -> None:
        with controller.admit(serial=serial, lane=AdbLane.INTERACTIVE):
            if announce:
                interactive_started.wait(timeout=1)
            release.wait(timeout=1)

    def maintenance() -> None:
        with controller.admit(serial="maintenance", lane=AdbLane.MAINTENANCE):
            maintenance_started.set()
            release_maintenance.wait(timeout=1)

    with ThreadPoolExecutor(max_workers=5) as pool:
        active = [
            pool.submit(
                interactive,
                "interactive-1",
                release_first,
                announce=True,
            ),
            pool.submit(
                interactive,
                "interactive-2",
                release_rest,
                announce=True,
            ),
            pool.submit(
                interactive,
                "interactive-3",
                release_rest,
                announce=True,
            ),
        ]
        interactive_started.wait(timeout=1)
        setup = pool.submit(maintenance)
        queued_control = pool.submit(
            interactive,
            "interactive-4",
            release_rest,
        )

        deadline = time.monotonic() + 0.2
        while controller.snapshot()["waiting"] < 2 and time.monotonic() < deadline:
            time.sleep(0.001)

        release_first.set()
        assert maintenance_started.wait(timeout=0.2)
        release_maintenance.set()
        release_rest.set()
        for future in [*active, setup, queued_control]:
            future.result(timeout=1)


def test_command_classification_keeps_control_ahead_of_setup() -> None:
    assert classify_adb_command(("shell", "input tap 10 20")) is AdbLane.INTERACTIVE
    assert classify_adb_command(("shell", "input keyevent KEYCODE_HOME")) is AdbLane.INTERACTIVE
    assert classify_adb_command(("push", "local", "remote")) is AdbLane.MAINTENANCE
    assert classify_adb_command(("install", "-r", "app.apk")) is AdbLane.MAINTENANCE
    assert classify_adb_command(
        ("shell", "chmod 755 /data/local/tmp/atx-agent"),
    ) is AdbLane.MAINTENANCE
    assert classify_adb_command(("forward", "tcp:1", "tcp:2")) is AdbLane.STARTUP
    assert classify_adb_command(("shell", "getprop ro.product.model")) is AdbLane.DEFAULT


def test_admission_snapshot_exposes_queue_and_capacity_metrics() -> None:
    controller = AdbAdmissionController(
        max_concurrency=2,
        reserved_interactive=1,
        max_heavy=1,
    )

    with controller.admit(serial="phone-a", lane=AdbLane.DEFAULT):
        active = controller.snapshot()

    completed = controller.snapshot()

    assert active["active"] == 1
    assert active["max_active"] == 1
    assert completed["active"] == 0
    assert completed["completed"] == 1
    assert completed["queue_wait_samples"] == 1
    assert completed["queue_wait_p95_ms"] >= 0


def test_heavy_setup_is_bounded_across_many_phones() -> None:
    controller = AdbAdmissionController(
        max_concurrency=5,
        reserved_interactive=1,
        max_heavy=2,
    )
    release = threading.Event()
    started = 0
    max_started = 0
    two_started = threading.Event()
    third_started = threading.Event()
    lock = threading.Lock()

    def heavy(serial: str) -> None:
        nonlocal started, max_started
        with controller.admit(serial=serial, lane=AdbLane.STARTUP):
            with lock:
                started += 1
                max_started = max(max_started, started)
                if started == 2:
                    two_started.set()
                if serial == "phone-c":
                    third_started.set()
            release.wait(timeout=1)
            with lock:
                started -= 1

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(heavy, "phone-a")
        second = pool.submit(heavy, "phone-b")
        assert two_started.wait(timeout=0.2)
        third = pool.submit(heavy, "phone-c")
        assert not third_started.wait(timeout=0.05)
        release.set()
        first.result(timeout=1)
        second.result(timeout=1)
        third.result(timeout=1)

    assert max_started == 2
    assert third_started.is_set()


def test_mock_19_phone_start_storm_keeps_control_available() -> None:
    controller = AdbAdmissionController(
        max_concurrency=12,
        reserved_interactive=2,
        max_heavy=3,
    )
    release_setup = threading.Event()
    first_wave_started = threading.Event()
    control_started = threading.Event()
    active_heavy = 0
    max_active_heavy = 0
    completed: set[str] = set()
    lock = threading.Lock()

    def start_phone(serial: str) -> None:
        nonlocal active_heavy, max_active_heavy
        with controller.admit(serial=serial, lane=AdbLane.STARTUP):
            with lock:
                active_heavy += 1
                max_active_heavy = max(max_active_heavy, active_heavy)
                if active_heavy == 3:
                    first_wave_started.set()
            release_setup.wait(timeout=1)
            with lock:
                active_heavy -= 1
                completed.add(serial)

    def control_phone() -> None:
        with controller.admit(
            serial="phone-control",
            lane=AdbLane.INTERACTIVE,
        ):
            control_started.set()

    with ThreadPoolExecutor(max_workers=20) as pool:
        starts = [
            pool.submit(start_phone, f"phone-{index:02d}")
            for index in range(19)
        ]
        assert first_wave_started.wait(timeout=0.2)
        control = pool.submit(control_phone)
        assert control_started.wait(timeout=0.2)
        release_setup.set()
        for future in starts:
            future.result(timeout=2)
        control.result(timeout=1)

    assert max_active_heavy == 3
    assert len(completed) == 19
