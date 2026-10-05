from __future__ import annotations

from types import SimpleNamespace

import pytest
from relay import u2_executor


class _FakeAdbDevice:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def install(self, source: str, nolaunch: bool = False, silent: bool = False) -> None:
        self.calls.append((source, nolaunch))


def _fake_dev() -> SimpleNamespace:
    return SimpleNamespace(adb_device=_FakeAdbDevice())


def test_install_apk_downloads_on_this_host_not_the_phone():
    dev = _fake_dev()
    u2_executor._OP_TABLE["install_apk"](dev, {"op": "install_apk", "url": "https://cdn/app.apk"})
    assert dev.adb_device.calls == [("https://cdn/app.apk", True)]


def test_install_apk_requires_a_source():
    with pytest.raises(ValueError):
        u2_executor._op_install_apk(_fake_dev(), {"op": "install_apk"})


def test_install_apk_fails_when_verify_package_is_absent(monkeypatch):
    monkeypatch.setattr(u2_executor, "_adb_shell", lambda *a, **kw: ("", 0))
    with pytest.raises(RuntimeError, match="not present after install"):
        u2_executor._op_install_apk(
            _fake_dev(),
            {"op": "install_apk", "url": "https://cdn/fb.apk",
             "verify_package": "com.example.app", "_serial": "abc"},
        )


def test_install_apk_passes_when_verify_package_is_present(monkeypatch):
    monkeypatch.setattr(
        u2_executor, "_adb_shell", lambda *a, **kw: ("package:/data/app/fb.apk", 0)
    )
    u2_executor._op_install_apk(
        _fake_dev(),
        {"op": "install_apk", "url": "https://cdn/fb.apk",
         "verify_package": "com.example.app", "_serial": "abc"},
    )
