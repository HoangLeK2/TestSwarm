from __future__ import annotations

import asyncio

from relay import adb as relay_adb
from relay import scrcpy_relay
from relay.scrcpy_relay import ScrcpyRelaySession


def test_probe_capabilities_batches_shell_and_reuses_cache(monkeypatch) -> None:
    relay_adb.invalidate_adb_device_cache("serial-1")
    calls: list[str] = []

    def fake_shell(serial: str, cmd: str, timeout: int = 30):
        calls.append(cmd)
        assert serial == "serial-1"
        assert "emit sdk" in cmd
        return (
            "\n".join(
                [
                    "__DF__sdk=35",
                    "__DF__android_version=15",
                    "__DF__abi=arm64-v8a",
                    "__DF__brand=vivo",
                    "__DF__model=V2352A",
                    "__DF__marketname=",
                    "__DF__marketing_name=Y200",
                    "__DF__vendor_marketname=",
                    "__DF__global_device_name=null",
                    "__DF__bluetooth_name=Farm Phone",
                    "__DF__persist_device_name=",
                    "__DF__hardware_serial=HW123",
                    "__DF__ro_serialno=SER123",
                    "__DF__build_fingerprint=vivo/fp",
                    "__DF__boot_id=boot-1",
                    "__DF__wm_size=1080x2400",
                    "__DF__mem_kb=8388608",
                    "__DF__ip_line=7: wlan0 inet 172.16.0.83/24 brd x",
                    "__DF__atx_agent=1",
                    "__DF__u2=1",
                    "__DF__stf=0",
                ]
            ),
            0,
        )

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    first = relay_adb._probe_capabilities("serial-1")
    second = relay_adb._probe_capabilities("serial-1")

    assert first == second
    assert first["sdk"] == "35"
    assert first["wlan_ip"] == "172.16.0.83"
    assert first["screen_width"] == 1080
    assert first["screen_height"] == 2400
    assert first["ram_gb"] == 8
    assert first["u2"] is True
    assert first["stf"] is False
    assert len(calls) == 1
    relay_adb.invalidate_adb_device_cache("serial-1")


def test_package_state_and_sha256_share_single_cached_probe(monkeypatch) -> None:
    relay_adb.invalidate_adb_device_cache("serial-1")
    calls: list[str] = []
    sha = "a" * 64

    def fake_shell(serial: str, cmd: str, timeout: int = 30):
        calls.append(cmd)
        assert "pm path" in cmd
        return (
            f"__DFPKG__{relay_adb._U2_PKG}\t"
            f"/data/app/u2/base.apk\t{sha}\n",
            0,
        )

    monkeypatch.setattr(relay_adb, "_adb_shell", fake_shell)

    assert relay_adb._pkg_installed("serial-1", relay_adb._U2_PKG) is True
    assert relay_adb._installed_pkg_sha256("serial-1", relay_adb._U2_PKG) == sha
    assert len(calls) == 1
    relay_adb.invalidate_adb_device_cache("serial-1")


def test_scrcpy_oem_hints_batch_and_global_cache(monkeypatch) -> None:
    scrcpy_relay.invalidate_scrcpy_oem_hints("SERIAL1")
    calls: list[tuple[object, ...]] = []

    def fake_adb(*args, **_kwargs):
        calls.append(args)
        assert args[0] == "shell"
        return "__DF__brand=vivo\n__DF__model=V2352A\n", 0

    def make_session() -> ScrcpyRelaySession:
        return ScrcpyRelaySession(
            serial="SERIAL1",
            max_fps=25,
            max_width=720,
            enable_control=True,
            port=27186,
            send_queue=asyncio.Queue(),
            loop=asyncio.new_event_loop(),
        )

    monkeypatch.setattr(scrcpy_relay, "_adb", fake_adb)
    first = make_session()
    second = make_session()
    try:
        assert first._load_device_oem_hints() == ("vivo", "v2352a")
        assert second._load_device_oem_hints() == ("vivo", "v2352a")
        assert len(calls) == 1
    finally:
        first._loop.close()
        second._loop.close()
        scrcpy_relay.invalidate_scrcpy_oem_hints("SERIAL1")
