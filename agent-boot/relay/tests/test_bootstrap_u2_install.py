from __future__ import annotations

import bootstrap
from relay import adb as relay_adb


def test_bootstrap_step_install_u2_skips_when_both_packages_exist(monkeypatch) -> None:
    calls: list[str] = []

    def fake_installed(pkg: str, serial: str) -> bool:
        return pkg in {bootstrap._U2_PKG, bootstrap._U2_TEST_PKG}

    monkeypatch.delenv("AGENT_BOOT_FORCE_U2_INSTALL", raising=False)
    monkeypatch.setattr(bootstrap, "_is_pkg_installed", fake_installed)
    monkeypatch.setattr(bootstrap, "find_u2_apks", lambda: (_raise("find_u2_apks should not run"), None))
    monkeypatch.setattr(bootstrap, "_adb_install", lambda *args, **kwargs: calls.append("install") or True)

    assert bootstrap.step_install_u2("serial-1", skip=False) is True
    assert calls == []


def test_bootstrap_step_install_u2_installs_only_missing_test_package(monkeypatch, tmp_path) -> None:
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
    assert installed == [bootstrap._U2_TEST_PKG]


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


def test_relay_bootstrap_u2_install_skips_when_packages_exist(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BOOT_FORCE_U2_INSTALL", raising=False)
    monkeypatch.setattr(relay_adb, "_pkg_installed", lambda serial, package: True)
    monkeypatch.setattr(relay_adb, "_assets_dir", lambda: _raise("_assets_dir should not run"))
    monkeypatch.setattr(relay_adb, "_run", lambda *args, **kwargs: _raise("adb push/install should not run"))

    msg, rc = relay_adb._install_u2_apks("serial-1")

    assert rc == 0
    assert msg == "u2 APKs already installed"


def _raise(message: str):
    raise AssertionError(message)
