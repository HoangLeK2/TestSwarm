from __future__ import annotations

import subprocess

import bootstrap
import pytest
from relay import adb as relay_adb


@pytest.fixture(autouse=True)
def _reset_relay_adb_forward_cache() -> None:
    relay_adb._ATX_FORWARD_CACHE.clear()
    relay_adb._ATX_FORWARD_FAIL_COUNT.clear()
    relay_adb._ATX_FORWARD_LAST_ERROR.clear()
    relay_adb._ATX_FORWARD_CREATE_RETRY_AFTER.clear()
    relay_adb._ATX_FORWARD_SERIAL_LOCKS.clear()
    relay_adb._ADB_COMMAND_STATS.clear()
    relay_adb._ATX_FORWARD_RECONCILE_NEXT_AT = 0.0


class _FakeUrlopenResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return b"pong"


def test_bootstrap_step_install_u2_skips_when_both_packages_exist(monkeypatch) -> None:
    calls: list[str] = []

    def fake_installed(pkg: str, serial: str) -> bool:
        return pkg in {bootstrap._U2_PKG, bootstrap._U2_TEST_PKG}

    monkeypatch.delenv("AGENT_BOOT_FORCE_U2_INSTALL", raising=False)
    monkeypatch.setattr(bootstrap, "_is_pkg_installed", fake_installed)
    monkeypatch.setattr(bootstrap, "find_u2_apks", lambda: (None, None))
    monkeypatch.setattr(bootstrap, "_adb_install", lambda *args, **kwargs: calls.append("install") or True)

    assert bootstrap.step_install_u2("serial-1", skip=False) is True
    assert calls == []


def test_bootstrap_step_install_u2_reinstalls_pair_when_test_package_missing(monkeypatch, tmp_path) -> None:
    main_apk = tmp_path / "app-uiautomator.apk"
    test_apk = tmp_path / "app-uiautomator-test.apk"
    installed: list[str] = []

    def fake_installed(pkg: str, serial: str) -> bool:
        return pkg == bootstrap._U2_PKG

    def fake_adb_install(apk_path, serial, label, **kwargs):
        installed.append(label)
        return True

    monkeypatch.delenv("AGENT_BOOT_FORCE_U2_INSTALL", raising=False)
    monkeypatch.setattr(bootstrap, "_is_pkg_installed", fake_installed)
    monkeypatch.setattr(bootstrap, "find_u2_apks", lambda: (main_apk, test_apk))
    monkeypatch.setattr(bootstrap, "_adb_install", fake_adb_install)

    assert bootstrap.step_install_u2("serial-1", skip=False) is True
    assert installed == [bootstrap._U2_PKG, bootstrap._U2_TEST_PKG]


def test_bootstrap_step_install_u2_reinstalls_pair_when_hash_mismatches(monkeypatch, tmp_path) -> None:
    main_apk = tmp_path / "app-uiautomator.apk"
    test_apk = tmp_path / "app-uiautomator-test.apk"
    main_apk.write_bytes(b"main-new")
    test_apk.write_bytes(b"test-new")
    installed: list[str] = []

    monkeypatch.delenv("AGENT_BOOT_FORCE_U2_INSTALL", raising=False)
    monkeypatch.setattr(bootstrap, "_is_pkg_installed", lambda pkg, serial: True)
    monkeypatch.setattr(bootstrap, "find_u2_apks", lambda: (main_apk, test_apk))
    monkeypatch.setattr(bootstrap, "_installed_apk_matches", lambda serial, pkg, apk: pkg == bootstrap._U2_PKG)
    monkeypatch.setattr(bootstrap, "_adb_install", lambda apk_path, serial, label, **kwargs: installed.append(label) or True)

    assert bootstrap.step_install_u2("serial-1", skip=False) is True
    assert installed == [bootstrap._U2_PKG, bootstrap._U2_TEST_PKG]


def test_relay_bootstrap_skips_atx_u2_restart_when_healthy(monkeypatch) -> None:
    monkeypatch.setattr(relay_adb, "_pkg_installed", lambda serial, package: True)
    monkeypatch.setattr(relay_adb, "_install_u2_apks", lambda serial: ("u2 APKs already installed", 0))
    monkeypatch.setattr(relay_adb, "_install_stf_apk", lambda serial: ("STFService already installed", 0))
    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: None)
    monkeypatch.setattr(relay_adb, "_grant_stf_permissions", lambda serial: [])
    monkeypatch.setattr(relay_adb, "_u2_atx_healthy", lambda serial: True)
    monkeypatch.setattr(
        relay_adb,
        "_restart_atx",
        lambda *args, **kwargs: _raise("_restart_atx should not run"),
    )
    monkeypatch.setattr(
        relay_adb,
        "_restart_u2",
        lambda *args, **kwargs: _raise("_restart_u2 should not run"),
    )
    monkeypatch.setattr(relay_adb, "_probe_capabilities", lambda serial: {"wlan_ip": "192.168.1.6"})
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: None)
    monkeypatch.setattr(relay_adb, "ensure_u2_input_ime", lambda serial: (True, "already default"))
    monkeypatch.setattr(
        relay_adb,
        "_adb_shell",
        lambda serial, cmd, timeout=30: ("arm64-v8a", 0)
        if "ro.product.cpu.abi" in cmd
        else ("present", 0),
    )

    output, rc = relay_adb._bootstrap_device("serial-1", timeout=60)

    assert rc == 0
    assert '"u2_ready": true' in output
    assert '"atx_ready": true' in output
    assert '"u2_ime_ready": true' in output


def test_u2_atx_health_rejects_wedged_http_even_when_ports_listen(monkeypatch) -> None:
    checked_ports: list[int] = []

    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "192.168.1.5")
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (False, "Remote end closed connection without response"))

    def fake_port_listening(serial: str, port: int, timeout: int = 5) -> bool:
        checked_ports.append(port)
        return True

    monkeypatch.setattr(relay_adb, "_device_port_listening", fake_port_listening)

    assert relay_adb._u2_atx_healthy("serial-1") is False
    assert checked_ports == []


def test_u2_atx_health_uses_jsonrpc_device_info_when_lan_ip_unavailable(monkeypatch) -> None:
    checked_ports: list[int] = []

    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "")
    monkeypatch.setattr(relay_adb, "_atx_jsonrpc_device_info", lambda *args, **kwargs: (True, "deviceInfo OK"))
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (False, "device LAN IP unavailable"))

    def fake_port_listening(serial: str, port: int, timeout: int = 5) -> bool:
        checked_ports.append(port)
        return True

    monkeypatch.setattr(relay_adb, "_device_port_listening", fake_port_listening)

    assert relay_adb._u2_atx_healthy("serial-1") is True
    assert checked_ports == []


def test_atx_http_ping_falls_back_to_adb_forward_when_lan_times_out(monkeypatch) -> None:
    adb_calls: list[tuple[tuple[str, ...], str | None, int]] = []
    urls: list[str] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        adb_calls.append((args, serial, timeout))
        if args == ("forward", "--list"):
            return "", 0
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\r\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    def fake_urlopen(url: str, timeout: float):
        urls.append(url)
        if url == "http://192.168.105.63:7912/ping":
            raise TimeoutError("timed out")
        if url == "http://host.docker.internal:43210/ping":
            return _FakeUrlopenResponse()
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(relay_adb, "_run", fake_run)
    monkeypatch.setattr(relay_adb.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")

    ok, msg = relay_adb._atx_http_ping("usb-serial", host="192.168.105.63")

    assert ok is True
    assert msg == "pong"
    assert urls == [
        "http://192.168.105.63:7912/ping",
        "http://host.docker.internal:43210/ping",
    ]
    assert adb_calls == [
        (("forward", "--list"), None, 5),
        (("forward", "tcp:0", "tcp:7912"), "usb-serial", 10),
    ]


def test_atx_http_ping_uses_adb_forward_when_lan_ip_unavailable(monkeypatch) -> None:
    adb_calls: list[tuple[tuple[str, ...], str | None, int]] = []
    urls: list[str] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        adb_calls.append((args, serial, timeout))
        if args == ("forward", "--list"):
            return "", 0
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    def fake_urlopen(url: str, timeout: float):
        urls.append(url)
        return _FakeUrlopenResponse()

    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "")
    monkeypatch.setattr(relay_adb, "_run", fake_run)
    monkeypatch.setattr(relay_adb.urllib.request, "urlopen", fake_urlopen)

    ok, msg = relay_adb._atx_http_ping("usb-serial")

    assert ok is True
    assert msg == "pong"
    assert urls == ["http://127.0.0.1:43210/ping"]
    assert adb_calls == [
        (("forward", "--list"), None, 5),
        (("forward", "tcp:0", "tcp:7912"), "usb-serial", 10),
    ]


def test_atx_http_ping_reuses_persistent_adb_forward(monkeypatch) -> None:
    adb_calls: list[tuple[tuple[str, ...], str | None, int]] = []
    urls: list[str] = []

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        adb_calls.append((args, serial, timeout))
        if args == ("forward", "--list"):
            return "", 0
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "43210\n", 0
        raise AssertionError(f"unexpected adb call: {args!r}")

    def fake_urlopen(url: str, timeout: float):
        urls.append(url)
        return _FakeUrlopenResponse()

    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "")
    monkeypatch.setattr(relay_adb, "_run", fake_run)
    monkeypatch.setattr(relay_adb.urllib.request, "urlopen", fake_urlopen)

    assert relay_adb._atx_http_ping("usb-serial")[0] is True
    assert relay_adb._atx_http_ping("usb-serial")[0] is True

    assert urls == [
        "http://127.0.0.1:43210/ping",
        "http://127.0.0.1:43210/ping",
    ]
    assert adb_calls == [
        (("forward", "--list"), None, 5),
        (("forward", "tcp:0", "tcp:7912"), "usb-serial", 10),
    ]


def test_atx_http_ping_reports_forward_failure(monkeypatch) -> None:
    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "")
    monkeypatch.setattr(
        relay_adb,
        "_run",
        lambda *args, **kwargs: ("cannot bind", 1),
    )

    ok, msg = relay_adb._atx_http_ping("usb-serial")

    assert ok is False
    assert msg == "adb forward failed: cannot bind"


def test_atx_http_ping_cools_down_repeated_forward_create_failures(monkeypatch) -> None:
    now = 100.0
    adb_calls: list[tuple[tuple[str, ...], str | None, int]] = []

    def fake_monotonic() -> float:
        return now

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        adb_calls.append((args, serial, timeout))
        if args == ("forward", "--list"):
            return "", 0
        if args == ("forward", "tcp:0", "tcp:7912"):
            return "cannot bind", 1
        raise AssertionError(f"unexpected adb call: {args!r}")

    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "")
    monkeypatch.setattr(relay_adb, "_run", fake_run)
    monkeypatch.setattr(relay_adb.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(relay_adb, "_ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS", 5.0)

    ok, msg = relay_adb._atx_http_ping("usb-serial")
    assert ok is False
    assert msg == "adb forward failed: cannot bind"

    ok, msg = relay_adb._atx_http_ping("usb-serial")
    assert ok is False
    assert msg == "adb forward failed: cannot bind"

    now = 106.0
    ok, msg = relay_adb._atx_http_ping("usb-serial")
    assert ok is False
    assert msg == "adb forward failed: cannot bind"

    assert adb_calls == [
        (("forward", "--list"), None, 5),
        (("forward", "tcp:0", "tcp:7912"), "usb-serial", 10),
        (("forward", "tcp:0", "tcp:7912"), "usb-serial", 10),
    ]


def test_atx_http_ping_does_not_forward_tcp_serial(monkeypatch) -> None:
    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "")

    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs):
        calls.append(args)
        return "", 1

    monkeypatch.setattr(relay_adb, "_run", fake_run)

    ok, msg = relay_adb._atx_http_ping("192.168.105.63:5555")

    assert ok is False
    assert msg == "adb forward unavailable for tcp serial"
    assert calls == []


def test_apply_u2_stability_settings_batches_adb_shell(monkeypatch) -> None:
    shell_calls: list[str] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]:
        shell_calls.append(cmd)
        return "", 0

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)
    monkeypatch.setattr(relay_adb, "ensure_u2_input_ime", lambda serial: (True, "ok"))

    relay_adb._apply_u2_stability_settings("serial-1")

    assert len(shell_calls) == 1
    assert "stay_on_while_plugged_in" in shell_calls[0]
    assert "accelerometer_rotation" in shell_calls[0]


def test_run_u2_recovery_cleanup_batches_shell(monkeypatch) -> None:
    shell_calls: list[tuple[str, int]] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]:
        shell_calls.append((cmd, timeout))
        return "", 0

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    relay_adb._run_u2_recovery_cleanup("serial-1", stop_atx=True)

    assert len(shell_calls) == 1
    script, timeout = shell_calls[0]
    assert timeout == 12
    assert "atx-agent server --stop" in script
    assert f"am force-stop {relay_adb._U2_TEST_PKG}" in script
    assert f"am force-stop {relay_adb._U2_PKG}" in script
    assert "pkill -9 -f" in script


def test_adb_command_stats_records_command_types(monkeypatch) -> None:
    def fake_subprocess_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["adb"],
            returncode=0,
            stdout=b"ok\n",
            stderr=b"",
        )

    monkeypatch.setattr(relay_adb.subprocess, "run", fake_subprocess_run)

    relay_adb._run("shell", "true", serial="serial-1")
    relay_adb._run("forward", "tcp:0", "tcp:7912", serial="serial-1")

    stats = relay_adb.adb_command_stats(reset=True)

    assert stats["cmd_shell"] == 1
    assert stats["cmd_forward"] == 1
    assert stats["lane_default"] == 1
    assert stats["lane_startup"] == 1
    assert relay_adb.adb_command_stats() == {}


def test_ensure_u2_input_ime_pins_adb_keyboard(monkeypatch) -> None:
    calls: list[str] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]:
        calls.append(cmd)
        return (
            "__DF__pkg=1\n"
            "__DF__ime=1\n"
            "__DF__current=com.google.android.inputmethod.latin/.LatinIME\n"
            f"__DF__final={relay_adb._U2_ADB_KEYBOARD_IME}\n",
            0,
        )

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    ok, msg = relay_adb.ensure_u2_input_ime("serial-1")

    assert ok is True
    assert msg == "enabled"
    assert len(calls) == 1
    assert f"ime enable {relay_adb._U2_ADB_KEYBOARD_IME}" in calls[0]
    assert (
        f"settings put secure default_input_method {relay_adb._U2_ADB_KEYBOARD_IME}"
        in calls[0]
    )


def test_ensure_u2_input_ime_skips_when_already_default(monkeypatch) -> None:
    calls: list[str] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]:
        calls.append(cmd)
        return (
            "__DF__pkg=1\n"
            "__DF__ime=1\n"
            f"__DF__current={relay_adb._U2_ADB_KEYBOARD_IME}\n"
            f"__DF__final={relay_adb._U2_ADB_KEYBOARD_IME}\n",
            0,
        )

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    ok, msg = relay_adb.ensure_u2_input_ime("serial-1")

    assert ok is True
    assert msg == "already default"
    assert len(calls) == 1


def test_relay_bootstrap_u2_install_skips_when_packages_exist_without_local_hash(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AGENT_BOOT_FORCE_U2_INSTALL", raising=False)
    monkeypatch.setattr(relay_adb, "_pkg_installed", lambda serial, package: True)
    monkeypatch.setattr(relay_adb, "_assets_dir", lambda: tmp_path)
    monkeypatch.setattr(relay_adb, "_run", lambda *args, **kwargs: _raise("adb push/install should not run"))

    msg, rc = relay_adb._install_u2_apks("serial-1")

    assert rc == 0
    assert msg == "u2 APKs already installed; hashes unavailable"


def test_relay_u2_install_reinstalls_pair_when_hash_mismatches(monkeypatch, tmp_path) -> None:
    apk_dir = tmp_path / "apks"
    apk_dir.mkdir()
    (apk_dir / "app-uiautomator.apk").write_bytes(b"main-new")
    (apk_dir / "app-uiautomator-test.apk").write_bytes(b"test-new")
    pushed: list[str] = []
    installed: list[str] = []

    monkeypatch.delenv("AGENT_BOOT_FORCE_U2_INSTALL", raising=False)
    monkeypatch.setattr(relay_adb, "_pkg_installed", lambda serial, package: True)
    monkeypatch.setattr(relay_adb, "_assets_dir", lambda: tmp_path)
    monkeypatch.setattr(relay_adb, "_installed_apk_matches", lambda serial, package, apk: package == relay_adb._U2_PKG)

    def fake_run(command: str, src: str, dst: str, **kwargs):
        pushed.append(dst)
        return ("", 0)

    def fake_shell(serial: str, cmd: str, timeout: int = 30):
        if "pm install" in cmd:
            installed.append(cmd)
            return ("Success", 0)
        return ("", 0)

    monkeypatch.setattr(relay_adb, "_run", fake_run)
    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    msg, rc = relay_adb._install_u2_apks("serial-1")

    assert rc == 0
    assert msg == "u2 APKs already installed; installed missing package(s)"
    assert pushed == ["/data/local/tmp/u2-main.apk", "/data/local/tmp/u2-test.apk"]
    assert len(installed) == 2


def test_device_port_listening_requires_listen_state(monkeypatch) -> None:
    commands: list[str] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 5):
        commands.append(cmd)
        return ("", 0)

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    assert relay_adb._device_port_listening("serial-1", 7912) is False
    assert '$4 == "0A"' in commands[0]


def test_restart_u2_waits_for_old_port_to_close_before_direct_start(monkeypatch) -> None:
    calls: list[str] = []
    rpc_states = iter([(False, "down"), (False, "down"), (True, "deviceInfo OK")])

    monkeypatch.setattr(relay_adb, "_U2_RESTART_HEALTHY_UNTIL", {})
    monkeypatch.setattr(relay_adb, "_u2_atx_healthy", lambda serial: False)
    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: None)
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: calls.append("lock"))
    monkeypatch.setattr(relay_adb.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (False, "down"))
    monkeypatch.setattr(relay_adb, "_atx_jsonrpc_device_info", lambda *args, **kwargs: next(rpc_states))

    def fake_adb_shell(serial: str, cmd: str, timeout: int = 30):
        calls.append(cmd)
        return ("", 0)

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_adb_shell)

    msg, rc = relay_adb._restart_u2("serial-1", timeout=5)

    assert rc == 0
    assert msg == "u2 started"
    instrument_pos = next(i for i, cmd in enumerate(calls) if "am instrument" in cmd)
    kill_pos = next(i for i, cmd in enumerate(calls) if "pkill -9 -f '[u]iautomator'" in cmd)
    assert kill_pos < instrument_pos
    assert f"-e class {relay_adb._U2_STUB_CLASS}" in calls[instrument_pos]
    assert "com.wetest.uia2.stub.Stub" not in calls[instrument_pos]
    assert calls[-1] == "lock"


def test_restart_u2_uses_atx_managed_restart_without_duplicate_instrument(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(relay_adb, "_U2_RESTART_HEALTHY_UNTIL", {})
    monkeypatch.setattr(relay_adb, "_u2_atx_healthy", lambda serial: False)
    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: None)
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: calls.append("lock"))
    monkeypatch.setattr(relay_adb.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (True, "pong"))
    monkeypatch.setattr(relay_adb, "_wait_for_atx_jsonrpc_device_info", lambda *args, **kwargs: (True, "deviceInfo OK"))

    def fake_adb_shell(serial: str, cmd: str, timeout: int = 30):
        calls.append(cmd)
        return ("", 0)

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_adb_shell)

    msg, rc = relay_adb._restart_u2("serial-1", timeout=5)

    assert rc == 0
    assert msg == "u2 started via atx-agent"
    assert not any("am instrument" in cmd for cmd in calls)
    assert calls[-1] == "lock"


def test_restart_u2_skips_when_atx_and_u2_are_healthy(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(relay_adb, "_U2_RESTART_HEALTHY_UNTIL", {})
    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: calls.append("settings"))
    monkeypatch.setattr(relay_adb, "_u2_atx_healthy", lambda serial: True)
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: calls.append("lock"))
    monkeypatch.setattr(relay_adb, "_run_u2_recovery_cleanup", lambda *args, **kwargs: calls.append("cleanup"))
    monkeypatch.setattr(relay_adb, "_adb_shell", lambda *args, **kwargs: calls.append("shell") or ("", 0))

    msg, rc = relay_adb._restart_u2("serial-healthy", timeout=5)

    assert rc == 0
    assert msg == "u2 already healthy; skipped restart"
    assert calls == ["settings", "lock"]


def test_restart_u2_skips_duplicate_after_recent_healthy_result(monkeypatch) -> None:
    calls: list[str] = []
    now = 100.0

    monkeypatch.setattr(relay_adb, "_U2_RESTART_HEALTHY_CACHE_SECONDS", 15)
    monkeypatch.setattr(relay_adb, "_U2_RESTART_HEALTHY_UNTIL", {})
    monkeypatch.setattr(relay_adb.time, "monotonic", lambda: now)
    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: calls.append("settings"))
    monkeypatch.setattr(relay_adb, "_u2_atx_healthy", lambda serial: calls.append("health") or True)
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: calls.append("lock"))
    monkeypatch.setattr(relay_adb, "_run_u2_recovery_cleanup", lambda *args, **kwargs: calls.append("cleanup"))

    assert relay_adb._restart_u2("serial-healthy", timeout=5) == (
        "u2 already healthy; skipped restart",
        0,
    )
    assert relay_adb._restart_u2("serial-healthy", timeout=5) == (
        "u2 recently healthy; skipped duplicate restart",
        0,
    )
    assert calls == ["settings", "health", "lock"]


def test_restart_atx_skips_when_atx_and_u2_are_healthy(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(relay_adb, "_U2_RESTART_HEALTHY_UNTIL", {})
    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: calls.append("settings"))
    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "192.0.2.10")
    monkeypatch.setattr(relay_adb, "_atx_jsonrpc_device_info", lambda *args, **kwargs: (True, "deviceInfo OK"))
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: calls.append("lock"))
    monkeypatch.setattr(relay_adb, "_run_u2_recovery_cleanup", lambda *args, **kwargs: calls.append("cleanup"))
    monkeypatch.setattr(relay_adb, "_adb_shell", lambda *args, **kwargs: calls.append("shell") or ("", 0))

    msg, rc = relay_adb._restart_atx("serial-healthy", timeout=5)

    assert rc == 0
    assert msg == "atx-agent and u2 already healthy; skipped restart"
    assert calls == ["settings", "lock"]


def test_restart_atx_delegates_to_u2_restart_when_atx_is_healthy(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: calls.append("settings"))
    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "192.0.2.10")
    monkeypatch.setattr(relay_adb, "_atx_jsonrpc_device_info", lambda *args, **kwargs: (False, "u2 down"))
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (True, "pong"))
    monkeypatch.setattr(relay_adb, "_restart_u2", lambda serial, timeout=60: calls.append("restart_u2") or ("u2 started", 0))
    monkeypatch.setattr(relay_adb, "_run_u2_recovery_cleanup", lambda *args, **kwargs: calls.append("cleanup"))
    monkeypatch.setattr(relay_adb, "_adb_shell", lambda *args, **kwargs: calls.append("shell") or ("", 0))

    msg, rc = relay_adb._restart_atx("serial-u2-missing", timeout=5)

    assert rc == 0
    assert msg == "atx-agent healthy; u2 started"
    assert calls == ["settings", "restart_u2"]


def _raise(message: str):
    raise AssertionError(message)
