from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import relay.adb as relay_adb
import relay.scrcpy_relay as scrcpy_mod
from relay.adb_admission import AdbAdmissionController, AdbLane
from relay.scrcpy_relay import ScrcpyRelaySession


def _set_remote_adb_env(monkeypatch) -> None:
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")
    monkeypatch.delenv("ADB_HOST", raising=False)
    monkeypatch.delenv("ADB_PORT", raising=False)


def _make_session() -> ScrcpyRelaySession:
    return ScrcpyRelaySession(
        serial="SERIAL1",
        max_fps=25,
        max_width=720,
        enable_control=True,
        port=27186,
        send_queue=asyncio.Queue(),
        loop=asyncio.new_event_loop(),
    )


@pytest.fixture(autouse=True)
def _isolate_scrcpy_jar_deployment_cache() -> Iterator[None]:
    scrcpy_mod.invalidate_scrcpy_server_jar("SERIAL1")
    yield
    scrcpy_mod.invalidate_scrcpy_server_jar("SERIAL1")


def test_scrcpy_session_missing_profile_uses_fleet_defaults() -> None:
    loop = asyncio.new_event_loop()
    try:
        session = ScrcpyRelaySession(
            serial="SERIAL1",
            max_fps=0,
            max_width=0,
            enable_control=True,
            port=27186,
            send_queue=asyncio.Queue(),
            loop=loop,
            bitrate=0,
        )

        assert session._max_fps == scrcpy_mod.SCRCPY_DEFAULT_MAX_FPS
        assert session._max_width == scrcpy_mod.SCRCPY_DEFAULT_MAX_WIDTH
        assert session._bitrate == scrcpy_mod.SCRCPY_DEFAULT_BITRATE
        assert session.matches_config(
            max_fps=0,
            max_width=0,
            enable_control=True,
            port=27186,
            bitrate=0,
            low_latency=False,
        )
    finally:
        loop.close()


def test_scrcpy_start_defers_jar_check_to_relay_thread(monkeypatch) -> None:
    session = _make_session()
    jar_checks: list[str] = []

    class DeferredThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            # Do not execute the target: this test only verifies that start()
            # stays non-blocking and leaves JAR verification to the relay loop.
            pass

    monkeypatch.setattr(
        session,
        "_ensure_server_jar_on_device",
        lambda: jar_checks.append("checked"),
    )
    monkeypatch.setattr(scrcpy_mod.threading, "Thread", DeferredThread)

    try:
        session.start()
        assert jar_checks == []
    finally:
        session._loop.close()


def test_scrcpy_jar_path_is_versioned_and_push_is_atomic(monkeypatch) -> None:
    session = _make_session()
    calls: list[tuple[object, ...]] = []

    def fake_adb(*args, **_kwargs):
        calls.append(args)
        if args and args[0] == "shell" and "stat -c" in args[1]:
            return "", 1
        return "", 0

    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)

    try:
        session._ensure_server_jar_on_device()
    finally:
        session._loop.close()

    remote_path = scrcpy_mod._SCRCPY_PATH_ON_DEVICE
    assert scrcpy_mod._BUNDLED_JAR_VERSION in remote_path
    assert ("shell", "mkdir -p /data/local/tmp/device-farm") in calls
    assert ("push", str(scrcpy_mod._BUNDLED_JAR), f"{remote_path}.tmp") in calls
    assert ("shell", f"mv -f {remote_path}.tmp {remote_path}") in calls


def test_scrcpy_jar_stat_timeout_does_not_trigger_a_push(monkeypatch) -> None:
    session = _make_session()
    calls: list[tuple[object, ...]] = []

    def fake_adb(*args, **_kwargs):
        calls.append(args)
        return "timeout 5s", -1

    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)

    try:
        with pytest.raises(RuntimeError, match="verify scrcpy JAR failed"):
            session._ensure_server_jar_on_device()
    finally:
        session._loop.close()

    assert len(calls) == 1
    assert calls[0][0] == "shell"
    assert "stat -c" in str(calls[0][1])


def test_scrcpy_jar_deploy_is_single_flight_per_phone_and_version(
    monkeypatch,
) -> None:
    first = _make_session()
    second = _make_session()
    scrcpy_mod.invalidate_scrcpy_server_jar("SERIAL1")
    push_started = threading.Event()
    release_push = threading.Event()
    stat_calls = 0
    push_calls = 0
    lock = threading.Lock()

    def fake_adb(*args, **_kwargs):
        nonlocal stat_calls, push_calls
        if args[0] == "shell" and "stat -c" in args[1]:
            with lock:
                stat_calls += 1
            return "", 1
        if args[0] == "push":
            with lock:
                push_calls += 1
            push_started.set()
            release_push.wait(timeout=1)
        return "", 0

    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            deploy_first = pool.submit(first._ensure_server_jar_on_device)
            assert push_started.wait(timeout=0.2)
            deploy_second = pool.submit(second._ensure_server_jar_on_device)
            assert not deploy_second.done()
            release_push.set()
            deploy_first.result(timeout=1)
            deploy_second.result(timeout=1)
    finally:
        scrcpy_mod.invalidate_scrcpy_server_jar("SERIAL1")
        first._loop.close()
        second._loop.close()

    assert stat_calls == 1
    assert push_calls == 1


def test_new_scrcpy_session_reuses_recent_jar_verification(monkeypatch) -> None:
    first = _make_session()
    expected_size = scrcpy_mod._BUNDLED_JAR.stat().st_size
    stat_calls = 0

    def fake_adb(*args, **_kwargs):
        nonlocal stat_calls
        if args[0] == "shell" and "stat -c" in args[1]:
            stat_calls += 1
            return str(expected_size), 0
        return "", 0

    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)

    try:
        first._ensure_server_jar_on_device()
        second = _make_session()
        try:
            second._ensure_server_jar_on_device()
        finally:
            second._loop.close()
    finally:
        first._loop.close()

    assert stat_calls == 1


def test_expired_scrcpy_jar_cache_revalidates_device(monkeypatch) -> None:
    session = _make_session()
    expected_size = scrcpy_mod._BUNDLED_JAR.stat().st_size
    stat_calls = 0

    def fake_adb(*args, **_kwargs):
        nonlocal stat_calls
        if args[0] == "shell" and "stat -c" in args[1]:
            stat_calls += 1
            return str(expected_size), 0
        return "", 0

    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)

    try:
        session._ensure_server_jar_on_device()
        key = (session._serial, session._jar_version)
        with scrcpy_mod._SCRCPY_JAR_DEPLOY_CONDITION:
            scrcpy_mod._SCRCPY_JAR_READY[key] = (
                time.monotonic()
                - scrcpy_mod.SCRCPY_SERVER_JAR_VERIFY_TTL_SECONDS
                - 1
            )
        session._ensure_server_jar_on_device()
    finally:
        session._loop.close()

    assert stat_calls == 2


def test_invalidated_scrcpy_jar_cache_revalidates_within_ttl(monkeypatch) -> None:
    session = _make_session()
    expected_size = scrcpy_mod._BUNDLED_JAR.stat().st_size
    stat_calls = 0

    def fake_adb(*args, **_kwargs):
        nonlocal stat_calls
        if args[0] == "shell" and "stat -c" in args[1]:
            stat_calls += 1
            return str(expected_size), 0
        return "", 0

    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)

    try:
        session._ensure_server_jar_on_device()
        session._ensure_server_jar_on_device()
        scrcpy_mod.invalidate_scrcpy_server_jar(session._serial)
        session._ensure_server_jar_on_device()
    finally:
        session._loop.close()

    assert stat_calls == 2


def test_adb_command_uses_remote_server_flags_from_socket(monkeypatch) -> None:
    _set_remote_adb_env(monkeypatch)

    assert relay_adb._adb_command("shell", "true", serial="SERIAL1") == [
        relay_adb._ADB,
        "-H",
        "host.docker.internal",
        "-P",
        "5037",
        "-s",
        "SERIAL1",
        "shell",
        "true",
    ]


def test_relay_adb_run_uses_remote_server_flags(monkeypatch) -> None:
    _set_remote_adb_env(monkeypatch)
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout=b"ok", stderr=b"", returncode=0)

    monkeypatch.setattr(relay_adb.subprocess, "run", fake_run)

    out, rc = relay_adb._run("shell", "echo ok", serial="SERIAL1")

    assert (out, rc) == ("ok", 0)
    assert calls == [[
        relay_adb._ADB,
        "-H",
        "host.docker.internal",
        "-P",
        "5037",
        "-s",
        "SERIAL1",
        "shell",
        "echo ok",
    ]]


def test_relay_adb_run_serializes_commands_for_the_same_phone(monkeypatch) -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    calls = 0
    lock = threading.Lock()

    def fake_run(_cmd, **_kwargs):
        nonlocal calls
        with lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered.set()
            release_first.wait(timeout=1)
        else:
            second_entered.set()
        return SimpleNamespace(stdout=b"ok", stderr=b"", returncode=0)

    monkeypatch.setattr(relay_adb.subprocess, "run", fake_run)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            relay_adb._run,
            "shell",
            "getprop ro.product.model",
            serial="SERIAL-SAME",
        )
        assert first_entered.wait(timeout=0.2)
        second = pool.submit(
            relay_adb._run,
            "shell",
            "getprop ro.product.brand",
            serial="SERIAL-SAME",
        )
        assert not second_entered.wait(timeout=0.05)
        release_first.set()
        assert first.result(timeout=1) == ("ok", 0)
        assert second.result(timeout=1) == ("ok", 0)

    assert second_entered.is_set()


def test_binary_adb_command_shares_the_same_per_phone_admission(monkeypatch) -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    binary_entered = threading.Event()
    calls = 0
    lock = threading.Lock()

    def fake_run(_cmd, **_kwargs):
        nonlocal calls
        with lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered.set()
            release_first.wait(timeout=1)
        else:
            binary_entered.set()
        return SimpleNamespace(stdout=b"ok", stderr=b"", returncode=0)

    monkeypatch.setattr(relay_adb.subprocess, "run", fake_run)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            relay_adb._run,
            "shell",
            "getprop ro.product.model",
            serial="SERIAL-BINARY",
        )
        assert first_entered.wait(timeout=0.2)
        binary = pool.submit(
            relay_adb._run_bytes,
            "exec-out",
            "screencap",
            "-p",
            serial="SERIAL-BINARY",
        )
        assert not binary_entered.wait(timeout=0.05)
        release_first.set()
        assert first.result(timeout=1) == ("ok", 0)
        assert binary.result(timeout=1) == (b"ok", 0)

    assert binary_entered.is_set()


def test_scrcpy_and_bootstrap_share_per_phone_admission(monkeypatch) -> None:
    bootstrap_entered = threading.Event()
    release_bootstrap = threading.Event()
    scrcpy_entered = threading.Event()
    calls = 0
    lock = threading.Lock()

    def fake_run(_cmd, **_kwargs):
        nonlocal calls
        with lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            bootstrap_entered.set()
            release_bootstrap.wait(timeout=1)
        else:
            scrcpy_entered.set()
        return SimpleNamespace(stdout=b"ok", stderr=b"", returncode=0)

    monkeypatch.setattr(relay_adb.subprocess, "run", fake_run)

    with ThreadPoolExecutor(max_workers=2) as pool:
        bootstrap = pool.submit(
            relay_adb._run,
            "shell",
            "getprop ro.product.cpu.abi",
            serial="SERIAL-SHARED",
        )
        assert bootstrap_entered.wait(timeout=0.2)
        scrcpy = pool.submit(
            scrcpy_mod._adb,
            "forward",
            "tcp:27186",
            "localabstract:scrcpy",
            serial="SERIAL-SHARED",
        )
        assert not scrcpy_entered.wait(timeout=0.05)
        release_bootstrap.set()
        assert bootstrap.result(timeout=1) == ("ok", 0)
        assert scrcpy.result(timeout=1) == ("ok", 0)

    assert scrcpy_entered.is_set()


def test_19_phone_scrcpy_storm_keeps_farm_control_available(monkeypatch) -> None:
    controller = AdbAdmissionController(
        max_concurrency=12,
        reserved_interactive=2,
        max_heavy=3,
    )
    monkeypatch.setattr(relay_adb, "adb_admission", controller.admit)
    monkeypatch.setattr(scrcpy_mod, "adb_admission", controller.admit)

    release_setup = threading.Event()
    first_wave_started = threading.Event()
    control_started = threading.Event()
    active_setup = 0
    max_active_setup = 0
    completed_setup = 0
    lock = threading.Lock()

    def fake_run(cmd, **_kwargs):
        nonlocal active_setup, max_active_setup, completed_setup
        if "push" in cmd:
            with lock:
                active_setup += 1
                max_active_setup = max(max_active_setup, active_setup)
                if active_setup == 3:
                    first_wave_started.set()
            release_setup.wait(timeout=2)
            with lock:
                active_setup -= 1
                completed_setup += 1
        elif "getprop ro.product.model" in cmd:
            control_started.set()
        return SimpleNamespace(stdout=b"ok", stderr=b"", returncode=0)

    monkeypatch.setattr(relay_adb.subprocess, "run", fake_run)

    with ThreadPoolExecutor(max_workers=20) as pool:
        starts = [
            pool.submit(
                scrcpy_mod._adb,
                "push",
                "scrcpy-server.jar",
                "/data/local/tmp/scrcpy-server.jar",
                serial=f"phone-{index:02d}",
            )
            for index in range(19)
        ]
        assert first_wave_started.wait(timeout=0.5)
        control = pool.submit(
            relay_adb._run,
            "shell",
            "getprop ro.product.model",
            serial="phone-control",
            lane=AdbLane.INTERACTIVE,
        )
        assert control_started.wait(timeout=0.5)
        release_setup.set()
        assert control.result(timeout=1) == ("ok", 0)
        for future in starts:
            assert future.result(timeout=2) == ("ok", 0)

    assert max_active_setup == 3
    assert completed_setup == 19


def test_viewer_scrcpy_push_runs_before_queued_bootstrap_push(
    monkeypatch,
) -> None:
    controller = AdbAdmissionController(
        max_concurrency=2,
        reserved_interactive=0,
        max_heavy=2,
    )
    monkeypatch.setattr(relay_adb, "adb_admission", controller.admit)
    monkeypatch.setattr(scrcpy_mod, "adb_admission", controller.admit)

    blockers_started = threading.Barrier(3)
    release_first = threading.Event()
    release_second = threading.Event()
    release_work = threading.Event()
    bootstrap_started = threading.Event()
    scrcpy_started = threading.Event()

    def fake_run(cmd, **_kwargs):
        if "blocker-first" in cmd:
            blockers_started.wait(timeout=1)
            release_first.wait(timeout=2)
        elif "blocker-second" in cmd:
            blockers_started.wait(timeout=1)
            release_second.wait(timeout=2)
        elif "bootstrap.apk" in cmd:
            bootstrap_started.set()
            release_work.wait(timeout=2)
        elif "scrcpy-server.jar" in cmd:
            scrcpy_started.set()
            release_work.wait(timeout=2)
        return SimpleNamespace(stdout=b"ok", stderr=b"", returncode=0)

    monkeypatch.setattr(relay_adb.subprocess, "run", fake_run)

    with ThreadPoolExecutor(max_workers=4) as pool:
        blockers = [
            pool.submit(
                relay_adb._run,
                "shell",
                "blocker-first",
                serial="phone-blocker-1",
                lane=AdbLane.DEFAULT,
            ),
            pool.submit(
                relay_adb._run,
                "shell",
                "blocker-second",
                serial="phone-blocker-2",
                lane=AdbLane.DEFAULT,
            ),
        ]
        blockers_started.wait(timeout=1)
        bootstrap = pool.submit(
            relay_adb._run,
            "push",
            "bootstrap.apk",
            "/data/local/tmp/bootstrap.apk",
            serial="phone-bootstrap",
        )
        viewer = pool.submit(
            scrcpy_mod._adb,
            "push",
            "scrcpy-server.jar",
            "/data/local/tmp/scrcpy-server.jar",
            serial="phone-viewer",
        )

        deadline = time.monotonic() + 0.2
        while controller.snapshot()["waiting"] < 2 and time.monotonic() < deadline:
            time.sleep(0.001)

        try:
            release_first.set()
            assert scrcpy_started.wait(timeout=0.2)
            assert not bootstrap_started.is_set()
        finally:
            release_work.set()
            release_second.set()

        for future in [*blockers, bootstrap, viewer]:
            assert future.result(timeout=1) == ("ok", 0)


def test_scrcpy_adb_run_uses_remote_server_flags(monkeypatch) -> None:
    _set_remote_adb_env(monkeypatch)
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout=b"ok", stderr=b"", returncode=0)

    monkeypatch.setattr(scrcpy_mod.subprocess, "run", fake_run)

    out, rc = scrcpy_mod._adb("forward", "tcp:27186", "localabstract:scrcpy", serial="SERIAL1")

    assert (out, rc) == ("ok", 0)
    assert calls == [[
        relay_adb._ADB,
        "-H",
        "host.docker.internal",
        "-P",
        "5037",
        "-s",
        "SERIAL1",
        "forward",
        "tcp:27186",
        "localabstract:scrcpy",
    ]]


def test_scrcpy_server_launch_uses_remote_server_flags(monkeypatch) -> None:
    _set_remote_adb_env(monkeypatch)
    session = _make_session()
    popen_calls: list[list[str]] = []

    def fake_adb(*args, **_kwargs):
        if args and args[0] == "forward":
            return "", 0
        return "", 1

    def fake_popen(cmd, **_kwargs):
        popen_calls.append(cmd)
        return SimpleNamespace(stdout=[])

    monkeypatch.setattr(session, "_kill_server", lambda: None)
    monkeypatch.setattr(session, "_ensure_server_jar_on_device", lambda: None)
    monkeypatch.setattr(session, "_load_device_oem_hints", lambda: ("", ""))
    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)
    monkeypatch.setattr(scrcpy_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(scrcpy_mod.time, "sleep", lambda _seconds: None)

    session._start_scrcpy_server()

    assert popen_calls
    assert popen_calls[0][:7] == [
        relay_adb._ADB,
        "-H",
        "host.docker.internal",
        "-P",
        "5037",
        "-s",
        "SERIAL1",
    ]
    assert popen_calls[0][7] == "shell"


def test_scrcpy_server_launch_disables_cleanup_by_default(monkeypatch) -> None:
    session = _make_session()
    popen_calls: list[list[str]] = []

    def fake_adb(*args, **_kwargs):
        if args and args[0] == "forward":
            return "", 0
        return "", 1

    def fake_popen(cmd, **_kwargs):
        popen_calls.append(cmd)
        return SimpleNamespace(stdout=[])

    monkeypatch.setattr(session, "_kill_server", lambda: None)
    monkeypatch.setattr(session, "_ensure_server_jar_on_device", lambda: None)
    monkeypatch.setattr(session, "_load_device_oem_hints", lambda: ("", ""))
    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)
    monkeypatch.setattr(scrcpy_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(scrcpy_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scrcpy_mod, "_SCRCPY_CLEANUP_DEFAULT", False)

    session._start_scrcpy_server()

    assert popen_calls
    assert "cleanup=false" in popen_calls[0][-1]


def test_scrcpy_server_launch_allows_cleanup_override(monkeypatch) -> None:
    session = _make_session()
    popen_calls: list[list[str]] = []

    def fake_adb(*args, **_kwargs):
        if args and args[0] == "forward":
            return "", 0
        return "", 1

    def fake_popen(cmd, **_kwargs):
        popen_calls.append(cmd)
        return SimpleNamespace(stdout=[])

    monkeypatch.setattr(session, "_kill_server", lambda: None)
    monkeypatch.setattr(session, "_ensure_server_jar_on_device", lambda: None)
    monkeypatch.setattr(session, "_load_device_oem_hints", lambda: ("", ""))
    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)
    monkeypatch.setattr(scrcpy_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(scrcpy_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scrcpy_mod, "_SCRCPY_CLEANUP_DEFAULT", True)

    session._start_scrcpy_server()

    assert popen_calls
    assert "cleanup=true" in popen_calls[0][-1]


def test_scrcpy_server_launch_omits_unsupported_turn_screen_on(monkeypatch) -> None:
    session = _make_session()
    popen_calls: list[list[str]] = []

    def fake_adb(*args, **_kwargs):
        if args and args[0] == "forward":
            return "", 0
        return "", 1

    def fake_popen(cmd, **_kwargs):
        popen_calls.append(cmd)
        return SimpleNamespace(stdout=[])

    monkeypatch.setattr(session, "_kill_server", lambda: None)
    monkeypatch.setattr(session, "_ensure_server_jar_on_device", lambda: None)
    monkeypatch.setattr(session, "_load_device_oem_hints", lambda: ("", ""))
    monkeypatch.setattr(scrcpy_mod, "_adb", fake_adb)
    monkeypatch.setattr(scrcpy_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(scrcpy_mod.time, "sleep", lambda _seconds: None)

    session._start_scrcpy_server()

    assert popen_calls
    assert "stay_awake=true" in popen_calls[0][-1]
    assert "turn_screen_on=" not in popen_calls[0][-1]
