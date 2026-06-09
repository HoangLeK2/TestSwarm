"""adb forward TCP host resolution for Docker / remote adb server."""
from __future__ import annotations

import relay.scrcpy_relay as mod


def test_adb_forward_host_local_default(monkeypatch) -> None:
    monkeypatch.delenv("SCRCPY_FORWARD_HOST", raising=False)
    monkeypatch.delenv("ADB_SERVER_SOCKET", raising=False)
    monkeypatch.delenv("ADB_HOST", raising=False)
    assert mod._adb_forward_host() == "127.0.0.1"


def test_adb_forward_host_from_adb_server_socket(monkeypatch) -> None:
    monkeypatch.delenv("SCRCPY_FORWARD_HOST", raising=False)
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")
    assert mod._adb_forward_host() == "host.docker.internal"


def test_adb_forward_host_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("ADB_SERVER_SOCKET", "tcp:host.docker.internal:5037")
    monkeypatch.setenv("SCRCPY_FORWARD_HOST", "10.0.0.5")
    assert mod._adb_forward_host() == "10.0.0.5"
