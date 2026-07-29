from __future__ import annotations

import asyncio
from types import SimpleNamespace

import relay.adb as relay_adb
import relay.scrcpy_relay as scrcpy_mod
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
