from __future__ import annotations

import bootstrap
from relay import adb as relay_adb


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


def test_u2_atx_health_falls_back_to_ports_when_lan_ip_unavailable(monkeypatch) -> None:
    checked_ports: list[int] = []

    monkeypatch.setattr(relay_adb, "_resolve_device_lan_ip", lambda serial: "")
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (False, "device LAN IP unavailable"))

    def fake_port_listening(serial: str, port: int, timeout: int = 5) -> bool:
        checked_ports.append(port)
        return True

    monkeypatch.setattr(relay_adb, "_device_port_listening", fake_port_listening)

    assert relay_adb._u2_atx_healthy("serial-1") is True
    assert checked_ports == [7912, 9008]


def test_ensure_u2_input_ime_pins_adb_keyboard(monkeypatch) -> None:
    calls: list[str] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]:
        calls.append(cmd)
        if cmd == "ime list -s -a":
            return relay_adb._U2_ADB_KEYBOARD_IME, 0
        if cmd == "settings get secure default_input_method":
            if len([c for c in calls if c == "settings get secure default_input_method"]) == 1:
                return "com.google.android.inputmethod.latin/.LatinIME", 0
            return relay_adb._U2_ADB_KEYBOARD_IME, 0
        return "", 0

    monkeypatch.setattr(relay_adb, "_pkg_installed", lambda serial, package: package == relay_adb._U2_PKG)
    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    ok, msg = relay_adb.ensure_u2_input_ime("serial-1")

    assert ok is True
    assert msg == "enabled"
    assert f"ime enable {relay_adb._U2_ADB_KEYBOARD_IME}" in calls
    assert f"settings put secure default_input_method {relay_adb._U2_ADB_KEYBOARD_IME}" in calls


def test_ensure_u2_input_ime_skips_when_already_default(monkeypatch) -> None:
    calls: list[str] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]:
        calls.append(cmd)
        if cmd == "ime list -s -a":
            return relay_adb._U2_ADB_KEYBOARD_IME, 0
        if cmd == "settings get secure default_input_method":
            return relay_adb._U2_ADB_KEYBOARD_IME, 0
        return "", 0

    monkeypatch.setattr(relay_adb, "_pkg_installed", lambda serial, package: True)
    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    ok, msg = relay_adb.ensure_u2_input_ime("serial-1")

    assert ok is True
    assert msg == "already default"
    assert not any(cmd.startswith("ime enable") for cmd in calls)


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

    assert relay_adb._device_port_listening("serial-1", 9008) is False
    assert '$4 == "0A"' in commands[0]


def test_restart_u2_waits_for_old_port_to_close_before_direct_start(monkeypatch) -> None:
    calls: list[str] = []
    port_states = iter([True, False, False, True])

    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: None)
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: calls.append("lock"))
    monkeypatch.setattr(relay_adb.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (False, "down"))
    monkeypatch.setattr(
        relay_adb,
        "_device_port_listening",
        lambda serial, port: next(port_states),
    )

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
    port_states = iter([True, False, False, True])

    monkeypatch.setattr(relay_adb, "_apply_u2_stability_settings", lambda serial: None)
    monkeypatch.setattr(relay_adb, "lock_portrait_rotation", lambda serial: calls.append("lock"))
    monkeypatch.setattr(relay_adb.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(relay_adb, "_atx_http_ping", lambda *args, **kwargs: (True, "pong"))
    monkeypatch.setattr(
        relay_adb,
        "_device_port_listening",
        lambda serial, port: next(port_states),
    )

    def fake_adb_shell(serial: str, cmd: str, timeout: int = 30):
        calls.append(cmd)
        return ("", 0)

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_adb_shell)

    msg, rc = relay_adb._restart_u2("serial-1", timeout=5)

    assert rc == 0
    assert msg == "u2 started via atx-agent"
    assert not any("am instrument" in cmd for cmd in calls)
    assert calls[-1] == "lock"


def _raise(message: str):
    raise AssertionError(message)
