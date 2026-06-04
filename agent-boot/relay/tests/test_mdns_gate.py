from __future__ import annotations

from relay import mdns


class _FakeZeroconf:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_mdns_discovery_disabled_by_default(monkeypatch):
    calls = []

    monkeypatch.delenv("AGENT_BOOT_MDNS", raising=False)
    monkeypatch.setattr(mdns, "_ZEROCONF_OK", True)
    monkeypatch.setattr(mdns, "Zeroconf", lambda: calls.append("zc") or _FakeZeroconf())
    monkeypatch.setattr(mdns, "ServiceBrowser", lambda *args: calls.append(args))

    assert mdns.start_mdns_discovery() is None
    assert calls == []


def test_mdns_discovery_enabled_by_env(monkeypatch):
    calls = []
    zc = _FakeZeroconf()

    monkeypatch.setenv("AGENT_BOOT_MDNS", "1")
    monkeypatch.setattr(mdns, "_ZEROCONF_OK", True)
    monkeypatch.setattr(mdns, "Zeroconf", lambda: calls.append("zc") or zc)
    monkeypatch.setattr(mdns, "ServiceBrowser", lambda *args: calls.append(args))

    assert mdns.start_mdns_discovery() is zc
    assert calls[0] == "zc"
    assert calls[1][0] is zc
    assert calls[1][1] == mdns._ADB_MDNS_SERVICE
