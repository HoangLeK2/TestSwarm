"""
tests/test_u2_bug_fixes.py — unit tests for the 5 bug fixes in u2_jsonrpc.py
and api/routes/device_control/device_ui.py.

Bug 1 [High]  : _find_element_xpath() ignores caller timeout → page_source blocked forever
Bug 2 [High]  : xpath element gestures (drag_to/pinch_in/pinch_out) pass xpath string as text selector
Bug 3 [Medium]: Watcher _check_and_fire() calls self._client.click/press (main session)
Bug 4 [Medium]: /ui_elements route parses XML with stdlib ET directly
Bug 5 [Medium]: _best_selector() returns XPath for content-desc instead of native "description"

Run: pytest tests/test_u2_bug_fixes.py -v
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from core.config import Config
from runtime.u2_xpath import XPathElementNotFoundError
from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.watchdog import WatchdogThread
from runtime.transports.u2_jsonrpc import (
    U2JsonRpcClient,
    _WatcherContext,
    _WatcherEntry,
)
from runtime.xml_utils import parse_xml

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SIMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="Home" resource-id="com.ex:id/home"
        class="android.widget.TextView" package="com.ex"
        content-desc="Home button" bounds="[0,0][100,50]"
        clickable="true" enabled="true"/>
  <node index="1" text="OK" resource-id="com.ex:id/ok"
        class="android.widget.Button" package="com.ex"
        content-desc="" bounds="[100,0][200,50]"
        clickable="true" enabled="true"/>
</hierarchy>"""


def _client(timeout: float = 5.0) -> U2JsonRpcClient:
    return U2JsonRpcClient(host="127.0.0.1", port=9008, timeout=timeout)


def _ok_response(result=None) -> Mock:
    resp = Mock()
    resp.ok = True
    resp.status_code = 200
    resp.text = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
    return resp


def _err_response(status: int = 500) -> Mock:
    resp = Mock()
    resp.ok = False
    resp.status_code = status
    resp.text = "server error"
    return resp


class _FakeRelay:
    def __init__(self, serials: list[str]) -> None:
        self._serials = list(serials)

    def relay_for_serial(self, serial: str):
        resolved = self.resolve_serial(serial)
        return object() if resolved in self._serials else None

    def resolve_serial(self, serial: str) -> str:
        if serial in self._serials:
            return serial
        ip = serial.rsplit(":", 1)[0] if ":" in serial else serial
        for known in self._serials:
            if ":" in known and known.rsplit(":", 1)[0] == ip:
                return known
        return serial

    def registered_relays(self) -> dict[str, list[str]]:
        return {"relay": list(self._serials)}


# ═══════════════════════════════════════════════════════════════════════════════
# Bug 1: xpath wait timeout capped to per-iteration remaining deadline
# ═══════════════════════════════════════════════════════════════════════════════

class TestXpathWaitTimeout:
    """_find_element_xpath must pass a deadline-aware timeout to page_source."""

    def test_page_source_timeout_never_exceeds_client_timeout(self):
        """Even with a large deadline, ps_timeout ≤ self._timeout."""
        c = _client(timeout=5.0)
        captured = []

        def fake_page_source(timeout=None, compressed=False):
            captured.append(timeout)
            return SIMPLE_XML

        c.page_source = fake_page_source
        c._find_element_xpath('//*[@text="Home"]', timeout=30.0)
        assert captured, "page_source was never called"
        assert all(t <= 5.0 for t in captured), (
            f"page_source timeout exceeded client timeout: {captured}"
        )

    def test_page_source_timeout_capped_when_deadline_is_near(self):
        """When only 0.3 s remain, ps_timeout ≈ 1.0 (max(0.5, 0.3+1.0)), not client timeout."""
        c = _client(timeout=20.0)
        captured = []

        # Element never found so loop will keep running until deadline
        def fake_page_source(timeout=None, compressed=False):
            captured.append(timeout)
            return ""  # not found

        c.page_source = fake_page_source
        # Use a very short wait so only 0-0.3 s remain on second iteration
        c._find_element_xpath('//*[@text="Missing"]', timeout=0.01)
        assert captured, "page_source was never called"
        # All recorded timeouts must be ≤ client timeout (20 s)
        assert all(t <= 20.0 for t in captured)

    def test_single_shot_calls_page_source_exactly_once(self):
        """timeout=0 → single shot, page_source called once regardless of match."""
        c = _client(timeout=5.0)
        call_count = {"n": 0}

        def fake_page_source(timeout=None, compressed=False):
            call_count["n"] += 1
            return ""

        c.page_source = fake_page_source
        result = c._find_element_xpath('//*[@text="X"]', timeout=0)
        assert result is None
        assert call_count["n"] == 1

    def test_returns_eid_when_xpath_matches(self):
        c = _client(timeout=5.0)
        c.page_source = lambda timeout=None, compressed=False: SIMPLE_XML
        result = c._find_element_xpath('//*[@text="Home"]', timeout=1.0)
        assert result == 'xpath:://*[@text="Home"]'

    def test_returns_none_when_xpath_never_matches(self):
        c = _client(timeout=5.0)
        c.page_source = lambda timeout=None, compressed=False: SIMPLE_XML
        result = c._find_element_xpath('//*[@text="NoSuchNode"]', timeout=0)
        assert result is None

    def test_page_source_error_does_not_abort_loop(self):
        """page_source exception is caught; loop retries until deadline."""
        c = _client(timeout=5.0)
        attempt = {"n": 0}

        def fake_page_source(timeout=None, compressed=False):
            attempt["n"] += 1
            if attempt["n"] == 1:
                raise RuntimeError("transient error")
            return SIMPLE_XML

        c.page_source = fake_page_source
        result = c._find_element_xpath('//*[@text="Home"]', timeout=2.0)
        assert result is not None
        assert attempt["n"] >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# Hierarchy coalescing: concurrent refresh calls share one u2 dump
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeviceClientHierarchyCoalescing:
    """Concurrent force refreshes should not fan out into repeated u2 XML dumps."""

    def test_force_refresh_bypasses_recent_hierarchy_cache(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._hierarchy_cache = (time.time(), "<hierarchy><node text=\"OLD\" /></hierarchy>")
        d.ensure_u2_healthy = lambda: True  # type: ignore[method-assign]

        class _FreshU2:
            def page_source(self, timeout=None, compressed=False):
                return "<hierarchy><node text=\"NEW\" /></hierarchy>"

        d._u2 = _FreshU2()

        xml = d.hierarchy_xml(force_refresh=True)

        assert xml is not None
        assert "NEW" in xml
        assert "OLD" not in xml

    def test_concurrent_force_refresh_waits_for_single_u2_dump(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        started = threading.Event()
        call_count = 0
        call_lock = threading.Lock()

        class _SlowU2:
            def page_source(self, timeout=None, compressed=False):
                nonlocal call_count
                with call_lock:
                    call_count += 1
                started.set()
                time.sleep(0.2)
                return SIMPLE_XML

        d.ensure_u2_healthy = lambda: True  # type: ignore[method-assign]
        d._u2 = _SlowU2()
        d._HIERARCHY_LOCK_WAIT_S = 0.05
        start_gate = threading.Event()

        def _call_hierarchy():
            start_gate.wait(timeout=1.0)
            return d.hierarchy_xml(force_refresh=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_call_hierarchy) for _ in range(5)]
            start_gate.set()
            assert started.wait(timeout=1.0)
            results = [f.result(timeout=2.0) for f in futures]

        assert all(result == results[0] for result in results)
        assert results[0] and "<hierarchy" in results[0]
        assert call_count == 1

    def test_failed_coalesced_refresh_does_not_return_expired_cache(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        started = threading.Event()
        d._hierarchy_cache = (time.time() - d._HIERARCHY_STALE_CACHE_TTL_S - 1.0, SIMPLE_XML)

        class _FailingU2:
            def page_source(self, timeout=None, compressed=False):
                started.set()
                time.sleep(0.2)
                return "<hierarchy />"

        d.ensure_u2_healthy = lambda: True  # type: ignore[method-assign]
        d._u2 = _FailingU2()
        d._HIERARCHY_LOCK_WAIT_S = 0.05
        d._request_u2_start_services = lambda reason: None  # type: ignore[method-assign]
        start_gate = threading.Event()

        def _call_hierarchy():
            start_gate.wait(timeout=1.0)
            return d.hierarchy_xml(force_refresh=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_call_hierarchy) for _ in range(2)]
            start_gate.set()
            assert started.wait(timeout=1.0)
            results = [f.result(timeout=2.0) for f in futures]

        assert results == [None, None]


# ═══════════════════════════════════════════════════════════════════════════════
# Hierarchy failure policy: slow XML must not disable coordinate control
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeviceClientHierarchyRecoveryPolicy:
    """A slow/failed hierarchy dump should not make live u2 touch unavailable."""

    def test_hierarchy_timeout_does_not_trigger_u2_recovery_or_drop_touch(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._agent_send = lambda msg: None
        d.ensure_u2_healthy = lambda *args, **kwargs: True  # type: ignore[method-assign]
        d._a11y_query = (  # type: ignore[method-assign]
            lambda *args, **kwargs: {"ok": False, "error": "relay timeout (4.0s)"}
        )
        d._recover_u2_ws_mode = Mock()  # type: ignore[method-assign]
        d._request_u2_start_services = Mock()  # type: ignore[method-assign]

        class _LiveButSlowHierarchyU2:
            def __init__(self):
                self.clicks: list[tuple[int, int]] = []

            def page_source(self, timeout=None, compressed=False):
                raise TimeoutError("dump_hierarchy timeout after 2.5s")

            def click(self, x, y):
                self.clicks.append((x, y))

        live_u2 = _LiveButSlowHierarchyU2()
        d._u2 = live_u2

        def _send_a11y_unavailable(_msg):
            d._ws_hierarchy_error = "accessibility_not_available"
            d._ws_hierarchy_event.set()

        d._send_to_agent = _send_a11y_unavailable  # type: ignore[method-assign]

        assert d.hierarchy_xml(force_refresh=True) is None
        assert d._u2 is live_u2
        d._recover_u2_ws_mode.assert_not_called()
        d._request_u2_start_services.assert_not_called()

        d.tap(11, 22)
        assert live_u2.clicks == [(11, 22)]

    def test_a11y_unavailable_uses_u2_batch_hierarchy_fallback(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._agent_send = lambda msg: None
        d.ensure_u2_healthy = lambda *args, **kwargs: True  # type: ignore[method-assign]
        d._a11y_query = Mock(return_value={"ok": False, "error": "accessibility_not_available"})  # type: ignore[method-assign]
        d._recover_u2_ws_mode = Mock()  # type: ignore[method-assign]
        d._request_u2_start_services = Mock()  # type: ignore[method-assign]

        class _HardFailedHierarchyU2:
            def page_source(self, timeout=None, compressed=False):
                raise RuntimeError("signal: killed")

        class _Batch:
            def __init__(self):
                self.actions: list[list[dict]] = []
                self.kwargs: list[dict] = []

            def batch(self, actions, timeout=30.0, cancel_event=None, **kwargs):
                self.actions.append(actions)
                self.kwargs.append(kwargs)
                return [{
                    "op": "dump_hierarchy",
                    "ok": True,
                    "value": "<hierarchy><node text=\"OK\" /></hierarchy>",
                }]

        batch = _Batch()
        d._u2 = _HardFailedHierarchyU2()
        d._u2_batch = batch

        def _send_a11y_unavailable(_msg):
            d._ws_hierarchy_error = "accessibility_not_available"
            d._ws_hierarchy_event.set()

        d._send_to_agent = _send_a11y_unavailable  # type: ignore[method-assign]

        xml = d.hierarchy_xml(force_refresh=True)

        assert xml is not None
        assert "<hierarchy" in xml
        assert batch.actions == [[{
            "op": "dump_hierarchy",
            "compressed": True,
            "timeout": d._U2_HIERARCHY_TIMEOUT,
            "force_fresh_xml": True,
        }]]
        assert batch.kwargs == [{"priority": None, "deadline_ms": None}]
        d._a11y_query.assert_not_called()
        d._recover_u2_ws_mode.assert_not_called()
        d._request_u2_start_services.assert_not_called()

    def test_hierarchy_u2_batch_fallback_forwards_priority_and_deadline(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._agent_send = lambda msg: None
        d.ensure_u2_healthy = lambda *args, **kwargs: True  # type: ignore[method-assign]
        d._recover_u2_ws_mode = Mock()  # type: ignore[method-assign]
        d._request_u2_start_services = Mock()  # type: ignore[method-assign]

        class _HardFailedHierarchyU2:
            def page_source(self, timeout=None, compressed=False):
                raise RuntimeError("signal: killed")

        class _Batch:
            def __init__(self):
                self.kwargs: list[dict] = []

            def batch(self, actions, timeout=30.0, cancel_event=None, **kwargs):
                self.kwargs.append(kwargs)
                return [{
                    "op": "dump_hierarchy",
                    "ok": True,
                    "value": "<hierarchy><node text=\"OK\" /></hierarchy>",
                }]

        batch = _Batch()
        d._u2 = _HardFailedHierarchyU2()
        d._u2_batch = batch

        xml = d.hierarchy_xml(
            force_refresh=True,
            priority="visible",
            deadline_ms=1500,
        )

        assert xml is not None
        assert batch.kwargs == [{"priority": "visible", "deadline_ms": 1500}]

    def test_hierarchy_prefers_direct_relay_http_dump_before_u2_batch(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._loop = object()
        d.ensure_u2_healthy = lambda *args, **kwargs: True  # type: ignore[method-assign]
        d._a11y_query = Mock(return_value={"ok": False, "error": "accessibility_not_available"})  # type: ignore[method-assign]

        class _HardFailedHierarchyU2:
            def page_source(self, timeout=None, compressed=False):
                raise RuntimeError("signal: killed")

        class _Batch:
            def batch(self, actions, timeout=30.0):
                raise AssertionError("u2_batch should not be called when direct HTTP dump works")

        class _Relay:
            def __init__(self):
                self.calls: list[tuple[str, str, str, float]] = []

            def resolve_serial(self, serial):
                return "172.16.0.83:5555"

            def relay_for_serial(self, serial):
                return object()

            async def u2_http(
                self,
                serial,
                method,
                path,
                body="",
                content_type="application/json",
                timeout=30.0,
                priority=None,
                deadline_ms=None,
            ):
                self.calls.append((serial, method, path, timeout))
                return {
                    "ok": True,
                    "status": 200,
                    "body": "<hierarchy><node text=\"HTTP\" /></hierarchy>",
                    "content_type": "text/xml",
                }

        relay = _Relay()
        d._u2 = _HardFailedHierarchyU2()
        d._u2_batch = _Batch()

        def run_now(coro, _loop):
            result = {}

            async def _run():
                result["value"] = await coro

            import asyncio

            asyncio.run(_run())
            return Mock(result=lambda timeout=None: result["value"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            xml = d.hierarchy_xml(force_refresh=True)

        assert xml is not None
        assert "HTTP" in xml
        assert relay.calls == [(
            "172.16.0.83:5555",
            "GET",
            "/dump/hierarchy?compressed=1",
            d._U2_HIERARCHY_TIMEOUT,
        )]
        d._a11y_query.assert_not_called()

    def test_hierarchy_direct_relay_http_dump_forwards_profile_options(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._loop = object()
        d.ensure_u2_healthy = lambda *args, **kwargs: True  # type: ignore[method-assign]
        d._a11y_query = Mock(return_value={"ok": False, "error": "accessibility_not_available"})  # type: ignore[method-assign]

        class _Batch:
            def batch(self, actions, timeout=30.0):
                raise AssertionError("u2_batch should not be called when direct HTTP dump works")

        class _Relay:
            def __init__(self):
                self.calls: list[tuple[str, str, str, float]] = []

            def resolve_serial(self, serial):
                return "172.16.0.83:5555"

            def relay_for_serial(self, serial):
                return object()

            async def u2_http(
                self,
                serial,
                method,
                path,
                body="",
                content_type="application/json",
                timeout=30.0,
                priority=None,
                deadline_ms=None,
            ):
                self.calls.append((serial, method, path, timeout))
                return {
                    "ok": True,
                    "status": 200,
                    "body": "<hierarchy><node text=\"HTTP\" /></hierarchy>",
                    "content_type": "text/xml",
                }

        relay = _Relay()
        d._u2_batch = _Batch()

        def run_now(coro, _loop):
            result = {}

            async def _run():
                result["value"] = await coro

            import asyncio

            asyncio.run(_run())
            return Mock(result=lambda timeout=None: result["value"])

        with patch.object(DeviceClient, "_U2_HIERARCHY_ROOT_IN_ACTIVE", True), \
                patch.object(DeviceClient, "_U2_HIERARCHY_MAX_DEPTH", 24), \
                patch.object(DeviceClient, "_U2_HIERARCHY_PRETTY", True), \
                patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            xml = d.hierarchy_xml(force_refresh=True)

        assert xml is not None
        assert "HTTP" in xml
        assert relay.calls == [(
            "172.16.0.83:5555",
            "GET",
            "/dump/hierarchy?compressed=1&root_in_active=1&max_depth=24&pretty=1",
            d._U2_HIERARCHY_TIMEOUT,
        )]


# ═══════════════════════════════════════════════════════════════════════════════
# U2 relay selection: current host must beat stale _adb_serial
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeviceClientU2RelaySelection:
    """U2 relay routing must not follow stale _adb_serial across phones."""

    def _device(self) -> DeviceClient:
        return DeviceClient(serial="logical-serial", index=0, config=Config())

    def test_prefers_adb_serial_over_current_u2_host(self):
        d = self._device()
        d._adb_serial = "172.16.0.86:5555"
        relay = _FakeRelay(["172.16.0.83:5555", "172.16.0.86:5555"])

        assert d._select_u2_relay_serial(relay, "172.16.0.83") == "172.16.0.86:5555"

    def test_uses_adb_serial_when_host_has_no_relay_and_multiple_devices_online(self):
        d = self._device()
        d._adb_serial = "172.16.0.86:5555"
        relay = _FakeRelay(["172.16.0.85:5555", "172.16.0.86:5555"])

        assert d._select_u2_relay_serial(relay, "172.16.0.83") == "172.16.0.86:5555"

    def test_allows_nat_adb_serial_when_it_is_the_only_online_relay(self):
        d = self._device()
        d._adb_serial = "172.16.0.86:5555"
        relay = _FakeRelay(["172.16.0.86:5555"])

        assert d._select_u2_relay_serial(relay, "203.0.113.10") == "172.16.0.86:5555"

    def test_resolve_relay_serial_prefers_adb_serial_over_host(self):
        d = self._device()
        d._u2_host = "172.16.0.83"
        d._adb_serial = "172.16.0.86:5555"
        relay = _FakeRelay(["172.16.0.83:5555", "172.16.0.86:5555"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay):
            assert d._resolve_relay_serial() == "172.16.0.86:5555"
        assert d._adb_serial == "172.16.0.86:5555"

    def test_local_config_does_not_force_u2_relay_when_relay_is_available(self):
        d = self._device()
        d.config.device.u2_always_tunnel = False
        d._u2_host = "172.16.0.83"
        d._adb_serial = "172.16.0.83:5555"
        relay = _FakeRelay(["172.16.0.83:5555"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay):
            assert d._should_force_u2_relay() is False

    def test_docker_tunnel_config_forces_u2_relay_when_relay_is_available(self):
        d = self._device()
        d.config.device.u2_always_tunnel = True
        d._u2_host = "203.0.113.10"
        d._adb_serial = "172.16.0.83:5555"
        relay = _FakeRelay(["172.16.0.83:5555"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay):
            assert d._should_force_u2_relay() is True


class TestRelayU2Bind:
    """Relay online must bind u2 host when WS hello raced ahead of relay."""

    def _device(self) -> DeviceClient:
        return DeviceClient(serial="logical-serial", index=0, config=Config())

    def test_u2_host_hint_from_adb_serial(self):
        d = self._device()
        d._adb_serial = "172.16.0.83:5555"
        assert d._u2_host_hint() == "172.16.0.83"

    def test_u2_host_hint_prefers_explicit_host(self):
        d = self._device()
        d._u2_host = "10.0.0.5"
        d._adb_serial = "172.16.0.83:5555"
        assert d._u2_host_hint() == "10.0.0.5"

    def test_bind_relay_u2_sets_host_and_adb_serial(self):
        d = self._device()
        d.config.device.u2_always_tunnel = True
        relay = _FakeRelay(["172.16.0.83:5555"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay):
            with patch.object(d, "_reconnect_u2") as reconnect:
                def _run_target(**kwargs):
                    mock = MagicMock()
                    mock.start = lambda: kwargs["target"]()
                    return mock

                with patch("runtime.core.device_client.threading.Thread", side_effect=_run_target):
                    ok = d.bind_relay_u2("172.16.0.83:5555", host="172.16.0.83")

        assert ok is True
        assert d._adb_serial == "172.16.0.83:5555"
        assert d._u2_host == "172.16.0.83"
        assert d._u2_reconnect_failed_at == 0.0
        reconnect.assert_called_once()

    def test_bind_relay_u2_skips_when_no_relay(self):
        d = self._device()
        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=None):
            assert d.bind_relay_u2("172.16.0.83:5555") is False

    def test_ensure_u2_healthy_uses_adb_serial_hint_without_u2_host(self):
        d = self._device()
        d.config.device.u2_always_tunnel = True
        d._adb_serial = "172.16.0.83:5555"
        relay = _FakeRelay(["172.16.0.83:5555"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay):
            with patch.object(d, "_reconnect_u2_atx", return_value=True) as atx:
                assert d.ensure_u2_healthy() is True
                atx.assert_called_once()

    def test_attach_preserves_relay_u2_on_ws_reconnect(self):
        from runtime.transports.u2_jsonrpc import _RelaySession

        d = self._device()
        fake_u2 = MagicMock()
        fake_u2._session = _RelaySession("172.16.0.83:5555", MagicMock(), MagicMock())
        d._u2 = fake_u2
        d._u2_batch = MagicMock()

        tunnels = MagicMock()
        tunnels.start_all.return_value = {"u2": 12345, "stfservice": 12346}
        with patch("runtime.core.device_client.TunnelSet", return_value=tunnels):
            d.attach_agent_sender(lambda msg: None)

        assert d._u2 is fake_u2
        assert d._u2_batch is not None

    def test_recover_u2_relay_mode_skips_restart(self):
        d = self._device()
        relay = _FakeRelay(["172.16.0.83:5555"])
        d._adb_serial = "172.16.0.83:5555"

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay):
            with patch.object(d, "_trigger_u2_restart_async") as restart:
                with patch.object(d, "_reconnect_u2") as reconnect:
                    def _run_target(**kwargs):
                        mock = MagicMock()
                        mock.start = lambda: kwargs["target"]()
                        return mock

                    with patch("runtime.core.device_client.threading.Thread", side_effect=_run_target):
                        d._recover_u2_ws_mode()

        restart.assert_not_called()
        reconnect.assert_called_once()

    def test_reconnect_skips_ws_tunnel_when_relay_active(self):
        d = DeviceClient(serial="10AE7S00HD002JK", index=0, config=Config())
        d._tunnel_ports = {"u2": 41511}
        relay = _FakeRelay(["10AE7S00HD002JK"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay):
            with patch.object(d, "_resolve_relay_u2_host", return_value=None):
                with patch.object(d, "_reconnect_u2_atx", return_value=False) as atx:
                    assert d._reconnect_u2_impl() is False
                    atx.assert_not_called()


class TestDeviceClientU2Recovery:
    """Legacy WS tunnel reconnect failures should trigger real recovery, not redial stale ports forever."""

    def test_legacy_reconnect_failure_requests_recovery_and_clears_ready_channel(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._tunnel_ports = {"u2": 45678}
        d._tunnels_ready_channels = {"u2"}
        d._agent_send = lambda msg: None
        recovery = Mock()
        d._recover_u2_ws_mode = recovery

        class FakeSession:
            def close(self):
                pass

        class FakeU2:
            def __init__(self, *args, **kwargs):
                self._session = FakeSession()
                self.settings = {}

            def implicitly_wait(self, _timeout):
                pass

            def verify(self, timeout):
                raise TimeoutError("u2 dead")

        with patch("runtime.core.device_client.U2JsonRpcClient", FakeU2):
            assert d._reconnect_u2() is False

        assert "u2" not in d._tunnels_ready_channels
        recovery.assert_called_once()
        assert d._recovery_reason == "u2_legacy_reconnect_failed"

    def test_atx_recovery_uses_relay_restart_u2(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._adb_serial = "172.16.0.83:5555"
        d._loop = object()
        d._agent_send = Mock()
        d._recovery_log = Mock()
        d._mark_recovery_end = Mock()
        relay = _FakeRelay(["172.16.0.83:5555"])
        restart_calls = []

        async def restart_u2(serial, timeout=60.0):
            restart_calls.append((serial, timeout))
            return True

        relay.restart_u2 = restart_u2

        def run_now(coro, _loop):
            asyncio.run(coro)
            return SimpleNamespace()

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            d._recover_u2_ws_mode()

        assert restart_calls == [("172.16.0.83:5555", 60.0)]
        d._agent_send.assert_not_called()

    def test_hierarchy_empty_reply_triggers_relay_restart_u2_without_host(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._adb_serial = "logical-serial"
        d._loop = object()
        d._agent_send = Mock()
        d._mark_recovery_start = Mock()
        d._recovery_log = Mock()
        d._mark_recovery_end = Mock()
        d._relay_u2_bind_at = time.monotonic() - 60.0
        relay = _FakeRelay(["logical-serial"])
        restart_calls = []

        async def restart_u2(serial, timeout=60.0):
            restart_calls.append((serial, timeout))
            return True

        relay.restart_u2 = restart_u2

        def run_now(coro, _loop):
            asyncio.run(coro)
            return SimpleNamespace()

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            d._note_hierarchy_relay_u2_failure("Remote end closed connection without response")
            assert restart_calls == []
            d._note_hierarchy_relay_u2_failure("Remote end closed connection without response")

        assert restart_calls == [("logical-serial", 60.0)]
        d._agent_send.assert_not_called()
        assert d._hierarchy_last_u2_failure_kind == "hard"

    def test_restart_u2_failure_escalates_to_restart_atx(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._adb_serial = "logical-serial"
        d._loop = object()
        relay = _FakeRelay(["logical-serial"])
        restart_u2_calls = []
        restart_atx = Mock()
        d._trigger_atx_restart_async = restart_atx

        async def restart_u2(serial, timeout=60.0):
            restart_u2_calls.append((serial, timeout))
            return False

        relay.restart_u2 = restart_u2

        def run_now(coro, _loop):
            asyncio.run(coro)
            return SimpleNamespace()

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            assert d._trigger_u2_restart_async("") is True

        assert restart_u2_calls == [("logical-serial", 60.0)]
        restart_atx.assert_called_once_with("")

    def test_atx_502_triggers_u2_restart_not_atx_restart(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._trigger_u2_restart_async = Mock(return_value=True)
        d._trigger_atx_restart_async = Mock()

        class FakeSession:
            def close(self):
                pass

        class FakeU2:
            def __init__(self, *args, **kwargs):
                self._session = FakeSession()
                self.settings = {}

            def implicitly_wait(self, _timeout):
                pass

            def verify(self, timeout):
                raise RuntimeError("JSON-RPC HTTP 502 for method='deviceInfo': 'Bad Gateway'")

        with patch("runtime.core.device_client.U2JsonRpcClient", FakeU2):
            assert d._reconnect_u2_atx() is False

        d._trigger_u2_restart_async.assert_called_once_with("172.16.0.83")
        d._trigger_atx_restart_async.assert_not_called()

    def test_atx_restart_failure_skips_recovery_poll_when_relay_disconnected(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._adb_serial = "172.16.0.83:5555"
        d._loop = object()
        relay = _FakeRelay(["172.16.0.83:5555"])

        async def restart_atx(serial, timeout=30.0):
            relay._serials.clear()
            return False

        relay.restart_atx = restart_atx

        def run_now(coro, _loop):
            asyncio.run(coro)
            return SimpleNamespace()

        with patch(
            "runtime.transports.adb_relay_server.get_relay_manager",
            return_value=relay,
        ):
            with patch(
                "runtime.core.device_client.asyncio.run_coroutine_threadsafe",
                side_effect=run_now,
            ):
                with patch("runtime.core.device_client.threading.Thread") as thread_cls:
                    d._trigger_atx_restart_async("172.16.0.83")

        thread_cls.assert_not_called()

    def test_u2_touch_failure_triggers_async_recovery_in_atx_mode(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._u2_host = "172.16.0.83"
        d._u2 = object()
        d._recover_u2_ws_mode = Mock()

        ok = d._try_u2_tap_impl(lambda: (_ for _ in ()).throw(RuntimeError("u2 killed")))

        assert ok is False
        assert d._u2 is None
        d._recover_u2_ws_mode.assert_called_once()


class TestDeviceClientOpenUrl:
    def test_open_url_prefers_u2_batch_when_available(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._loop = object()
        d._agent_send = Mock()
        d._u2_batch = Mock()
        d._u2_batch.batch.return_value = [{"op": "open_url", "ok": True}]
        d._open_url_via_adb_relay = Mock(return_value=True)

        d.open_url("https://example.com/path?q=1", package="com.android.chrome")

        d._agent_send.assert_not_called()
        d._open_url_via_adb_relay.assert_not_called()
        d._u2_batch.batch.assert_called_once_with(
            [{"op": "open_url", "url": "https://example.com/path?q=1"}],
            timeout=10.0,
            cancel_event=None,
            priority="visible",
            deadline_ms=2000,
        )

    def test_open_url_falls_back_to_adb_relay_when_u2_batch_unavailable(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._loop = object()
        d._agent_send = Mock()
        relay = _FakeRelay(["logical-serial"])
        relay.adb_shell = Mock()
        future = Mock()
        future.result.return_value = "Starting: Intent"

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", return_value=future):
            d.open_url("https://example.com/path?q=1", package="com.android.chrome")

        d._agent_send.assert_not_called()
        relay.adb_shell.assert_called_once()
        _, args, kwargs = relay.adb_shell.mock_calls[0]
        assert args[0] == "logical-serial"
        assert "android.intent.action.VIEW" in args[1]
        assert "https://example.com/path?q=1" in args[1]
        assert "-p com.android.chrome" in args[1]
        assert kwargs["timeout"] == 10.0

    def test_open_url_agent_timeout_retries_u2_batch_before_adb(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._agent_send = Mock()
        d._open_url_result_event = Mock()
        d._open_url_result_event.wait.return_value = False
        d._open_url_via_u2_batch = Mock(side_effect=[False, True])
        d._open_url_via_adb_relay = Mock(return_value=False)

        d.open_url("https://example.com")

        d._agent_send.assert_called_once()
        assert d._agent_send.call_args.args[0]["type"] == "open_url"
        assert d._open_url_via_u2_batch.call_count == 2
        d._open_url_via_adb_relay.assert_called_once()


class TestDeviceClientLaunchApp:
    def test_launch_app_prefers_agent_boot_u2_batch_and_waits_for_foreground(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._loop = object()
        d._agent_send = Mock()
        d._u2_batch = Mock()
        d._u2_batch.batch.return_value = [
            {"op": "app_start", "ok": True},
            {"op": "app_wait", "ok": True, "value": 321},
        ]
        relay = _FakeRelay(["logical-serial"])
        relay.adb_shell = Mock()

        with patch(
            "runtime.transports.adb_relay_server.get_relay_manager",
            return_value=relay,
        ):
            d.launch_app("com.facebook.katana")

        d._u2_batch.batch.assert_called_once_with(
            [
                {
                    "op": "app_start",
                    "package": "com.facebook.katana",
                    "stop_before": False,
                    "use_monkey": False,
                },
                {
                    "op": "app_wait",
                    "package": "com.facebook.katana",
                    "front": True,
                    "timeout": 8.0,
                },
            ],
            timeout=15.0,
            cancel_event=None,
            priority="visible",
            deadline_ms=3000,
        )
        relay.adb_shell.assert_not_called()
        d._agent_send.assert_not_called()

    def test_launch_app_falls_back_to_adb_when_agent_boot_u2_batch_fails(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._loop = object()
        d._agent_send = Mock()
        d._u2_batch = Mock()
        d._u2_batch.batch.side_effect = RuntimeError("u2 unavailable")
        relay = _FakeRelay(["logical-serial"])
        relay.adb_shell = Mock()
        future = Mock()
        future.result.return_value = "Starting: Intent"

        with (
            patch(
                "runtime.transports.adb_relay_server.get_relay_manager",
                return_value=relay,
            ),
            patch(
                "runtime.core.device_client.asyncio.run_coroutine_threadsafe",
                return_value=future,
            ),
        ):
            d.launch_app("com.facebook.katana")

        d._u2_batch.batch.assert_called_once()
        relay.adb_shell.assert_called_once()
        d._agent_send.assert_not_called()

    def test_launch_app_tries_package_fallbacks_with_u2_batch_before_adb(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._loop = object()
        d._agent_send = Mock()
        d._u2_batch = Mock()
        d._u2_batch.batch.side_effect = [
            [
                {"op": "app_start", "ok": True},
                {"op": "app_wait", "ok": False, "value": 0},
            ],
            [
                {"op": "app_start", "ok": True},
                {"op": "app_wait", "ok": True, "value": 321},
            ],
        ]
        relay = _FakeRelay(["logical-serial"])
        relay.adb_shell = Mock()

        with patch(
            "runtime.transports.adb_relay_server.get_relay_manager",
            return_value=relay,
        ):
            d.launch_app(
                "com.zhiliaoapp.musically",
                package_fallbacks=["com.ss.android.ugc.trill"],
            )

        assert d._u2_batch.batch.call_count == 2
        first_actions = d._u2_batch.batch.call_args_list[0].args[0]
        second_actions = d._u2_batch.batch.call_args_list[1].args[0]
        assert first_actions[0]["package"] == "com.zhiliaoapp.musically"
        assert first_actions[1]["package"] == "com.zhiliaoapp.musically"
        assert second_actions[0]["package"] == "com.ss.android.ugc.trill"
        assert second_actions[1]["package"] == "com.ss.android.ugc.trill"
        relay.adb_shell.assert_not_called()
        d._agent_send.assert_not_called()

    def test_launch_app_can_skip_adb_fallback_after_u2_batch_failure(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._loop = object()
        d._agent_send = Mock()
        d._u2_batch = Mock()
        d._u2_batch.batch.side_effect = RuntimeError("u2 unavailable")
        relay = _FakeRelay(["logical-serial"])
        relay.adb_shell = Mock()

        with patch(
            "runtime.transports.adb_relay_server.get_relay_manager",
            return_value=relay,
        ):
            d.launch_app("com.facebook.katana", adb_fallback=False)

        d._u2_batch.batch.assert_called_once()
        relay.adb_shell.assert_not_called()
        d._agent_send.assert_called_once_with(
            {
                "type": "launch_app",
                "package": "com.facebook.katana",
                "serial": "logical-serial",
            }
        )


class TestWatchdogAtxProbe:
    """Docker/agent-boot watchdog probes must use relay before direct TCP."""

    def test_ready_relay_without_scrcpy_stays_healthy(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d.state = DeviceState.READY
        d._agent_send = None
        d._scrcpy_active = False
        d.reconnect_attempts = 2
        relay = _FakeRelay(["logical-serial"])

        wd = WatchdogThread(manager=Mock(), config=Config())
        wd._bad_since[d.serial] = time.monotonic()

        with patch(
            "runtime.transports.adb_relay_server.get_relay_manager",
            return_value=relay,
        ):
            wd._check_device(d)

        assert d.serial not in wd._bad_since
        assert d.reconnect_attempts == 0
        assert d.state == DeviceState.READY

    def test_relay_probe_success_does_not_mark_atx_miss(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d._adb_serial = "172.16.0.86:5555"
        d._loop = object()
        relay = _FakeRelay(["172.16.0.83:5555", "172.16.0.86:5555"])
        relay.u2_http = Mock(return_value={"ok": True})

        wd = WatchdogThread(manager=Mock(), config=Config())
        future = Mock()
        future.result.return_value = {"ok": True}

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.watchdog.asyncio.run_coroutine_threadsafe", return_value=future), \
                patch("runtime.core.watchdog.socket.create_connection") as connect:
            assert wd._probe_atx_agent_alive(d, "172.16.0.83") is True

        connect.assert_not_called()

    def test_ready_agent_probes_relay_atx_even_when_u2_session_missing(self):
        d = DeviceClient(serial="logical-serial", index=0, config=Config())
        d.state = DeviceState.READY
        d._agent_send = Mock()
        d._u2 = None
        d._has_active_relay = Mock(return_value=True)

        wd = WatchdogThread(manager=Mock(), config=Config())
        wd._check_atx_agent = Mock()

        wd._check_device(d)

        wd._check_atx_agent.assert_called_once_with(d, "")


# ═══════════════════════════════════════════════════════════════════════════════
# Bug 2: xpath element gestures resolve bounds / raise NotImplementedError
# ═══════════════════════════════════════════════════════════════════════════════

class TestXpathElementGestures:
    """drag_to/pinch_in/pinch_out must not pass xpath string as a text selector."""

    # ── drag_to ─────────────────────────────────────────────────────────────

    _SAMPLE_XML = """<?xml version="1.0"?><hierarchy>
      <node text="Home" bounds="[0,0][100,50]"/>
      <node text="X" bounds="[0,0][10,10]"/>
      <node text="Map" bounds="[0,0][100,50]"/>
    </hierarchy>"""

    def test_drag_to_xpath_calls_drag_not_objdrag(self):
        """For xpath element, drag_to uses coordinate-based drag(), not objDrag(selector)."""
        c = _client()
        c.page_source = Mock(return_value=self._SAMPLE_XML)
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append((method, a))

        el = c.xpath('//*[@text="Home"]')
        el.drag_to(500, 500, duration=0.3)

        methods = [m for m, _ in rpc_calls]
        assert "drag" in methods, "Expected 'drag' RPC call"
        assert "objDrag" not in methods, "'objDrag' must not be called for xpath"

    def test_drag_to_xpath_passes_element_center(self):
        """drag_to derives source coordinates from element center, not xpath string."""
        c = _client()
        c.page_source = Mock(return_value=self._SAMPLE_XML)
        drag_args = {}

        def fake_rpc(method, *args, **kw):
            if method == "drag":
                drag_args["args"] = args

        c._rpc = fake_rpc
        c.xpath('//*[@text="X"]').drag_to(300, 400, duration=0.2)

        assert drag_args, "drag RPC never called"
        x1, y1 = drag_args["args"][0], drag_args["args"][1]
        assert x1 == 5, f"Expected source cx=5, got {x1}"
        assert y1 == 5, f"Expected source cy=5, got {y1}"

    def test_drag_to_xpath_raises_when_element_not_found(self):
        c = _client()
        c.page_source = Mock(return_value=self._SAMPLE_XML)
        with pytest.raises(XPathElementNotFoundError):
            c.xpath('//*[@text="Missing"]').drag_to(200, 200)

    def test_drag_to_xpath_raises_when_bounds_is_none(self):
        c = _client()
        c.page_source = Mock(return_value='<?xml version="1.0"?><hierarchy><node text="NoBounds"/></hierarchy>')
        with pytest.raises(RuntimeError, match="bounds"):
            c.xpath('//*[@text="NoBounds"]').drag_to(200, 200)

    def test_drag_to_non_xpath_calls_objdrag(self):
        """Non-xpath drag_to still uses objDrag(selector, …) — regression check."""
        c = _client()
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c(text="Home").drag_to(500, 500)
        assert "objDrag" in rpc_calls
        assert "drag" not in rpc_calls

    # ── pinch_in ────────────────────────────────────────────────────────────

    def test_pinch_in_xpath_delegates_to_native_text_selector(self):
        c = _client()
        c.page_source = Mock(return_value=self._SAMPLE_XML)
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c.xpath('//*[@text="Map"]').pinch_in()
        assert "pinchIn" in rpc_calls

    def test_pinch_in_non_xpath_calls_pinch_in_rpc(self):
        c = _client()
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c(text="Map").pinch_in(percent=50, steps=10)
        assert "pinchIn" in rpc_calls

    # ── pinch_out ───────────────────────────────────────────────────────────

    def test_pinch_out_xpath_delegates_to_native_text_selector(self):
        c = _client()
        c.page_source = Mock(return_value=self._SAMPLE_XML)
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c.xpath('//*[@text="Map"]').pinch_out()
        assert "pinchOut" in rpc_calls

    def test_pinch_out_non_xpath_calls_pinch_out_rpc(self):
        c = _client()
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c(text="Map").pinch_out(percent=50, steps=10)
        assert "pinchOut" in rpc_calls

    def test_pinch_in_without_native_attrs_raises(self):
        c = _client()
        c.page_source = Mock(return_value='<?xml version="1.0"?><hierarchy><node bounds="[0,0][10,10]"/></hierarchy>')
        with pytest.raises(RuntimeError, match="pinch_in"):
            c.xpath("//node[@bounds]").pinch_in()

    def test_pinch_out_without_native_attrs_raises(self):
        c = _client()
        c.page_source = Mock(return_value='<?xml version="1.0"?><hierarchy><node bounds="[0,0][10,10]"/></hierarchy>')
        with pytest.raises(RuntimeError, match="pinch_out"):
            c.xpath("//node[@bounds]").pinch_out()


# ═══════════════════════════════════════════════════════════════════════════════
# Bug 3: Watcher fires via dedicated session, not main client session
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherDedicatedSession:
    """_check_and_fire must NOT call self._client.click/press."""

    def _make_ctx(self) -> tuple[U2JsonRpcClient, _WatcherContext]:
        c = _client()
        return c, c.watchers

    def test_click_does_not_call_client_click(self):
        """Watcher click action goes through _rpc_dedicated, not client.click."""
        c, ctx = self._make_ctx()
        c.click = Mock()  # should never be called

        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        entry.click()

        ctx._rpc_dedicated = Mock(return_value=None)
        ctx._check_and_fire(root, entry)

        c.click.assert_not_called()
        ctx._rpc_dedicated.assert_called_once_with("click", 50, 25)  # center [0,0][100,50]

    def test_press_does_not_call_client_press(self):
        """Watcher press action goes through _rpc_dedicated, not client.press."""
        c, ctx = self._make_ctx()
        c.press = Mock()  # should never be called

        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        entry.press("back")

        ctx._rpc_dedicated = Mock(return_value=None)
        ctx._check_and_fire(root, entry)

        c.press.assert_not_called()
        # Should have tried RPC methods starting with pressKey/press/key/keyevent
        assert ctx._rpc_dedicated.called

    def test_press_tries_string_methods_in_order(self):
        """press falls back through pressKey → press → key → keyevent."""
        c, ctx = self._make_ctx()
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        entry.press("back")

        attempted = []

        def rpc_dedicated(method, *args):
            attempted.append(method)
            if method in ("pressKey", "press", "key", "keyevent"):
                raise RuntimeError("not supported")
            return None

        ctx._rpc_dedicated = rpc_dedicated
        ctx._check_and_fire(root, entry)  # should not raise

        # All string methods attempted; then keycode fallback
        assert "pressKey" in attempted
        assert "press" in attempted

    def test_press_keycode_fallback_for_known_key(self):
        """Known key (home/back) falls back to pressKeyCode after string methods fail."""
        c, ctx = self._make_ctx()
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        entry.press("home")

        succeeded = {}

        def rpc_dedicated(method, *args):
            if method in ("pressKey", "press", "key", "keyevent"):
                raise RuntimeError("not supported")
            # Accept keyCode methods
            succeeded["method"] = method
            return None

        ctx._rpc_dedicated = rpc_dedicated
        ctx._check_and_fire(root, entry)

        assert succeeded.get("method") in (
            "pressKeyCode", "pressKeycode", "keyCode", "keycode"
        ), f"Expected keycode method, got {succeeded}"

    def test_press_unknown_key_logs_warning_not_raises(self):
        """Unknown key that fails all methods logs warning instead of raising."""
        c, ctx = self._make_ctx()
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        entry.press("f13_unknown_key")

        ctx._rpc_dedicated = Mock(side_effect=RuntimeError("not supported"))
        # Must not raise
        ctx._check_and_fire(root, entry)

    def test_rpc_dedicated_uses_client_session_under_lock(self):
        """_rpc_dedicated posts through client._session while holding _http_lock."""
        c, ctx = self._make_ctx()
        c._session.post = Mock(return_value=_ok_response(result=None))

        ctx._rpc_dedicated("click", 50, 25)

        c._session.post.assert_called_once()

    def test_rpc_dedicated_raises_on_http_error(self):
        c, ctx = self._make_ctx()
        c._session.post = Mock(return_value=_err_response(500))
        with pytest.raises(RuntimeError, match="HTTP 500"):
            ctx._rpc_dedicated("click", 50, 25)

    def test_rpc_dedicated_raises_on_rpc_error(self):
        c, ctx = self._make_ctx()
        resp = Mock()
        resp.ok = True
        resp.status_code = 200
        resp.text = json.dumps({"jsonrpc": "2.0", "id": 0, "error": {"message": "UiObjectNotFound"}})
        c._session.post = Mock(return_value=resp)
        with pytest.raises(RuntimeError, match="watcher RPC error"):
            ctx._rpc_dedicated("click", 50, 25)

    def test_rpc_dedicated_sends_correct_payload(self):
        c, ctx = self._make_ctx()
        c._session.post = Mock(return_value=_ok_response(result=True))
        ctx._rpc_dedicated("click", 100, 200)

        _, kwargs = c._session.post.call_args
        payload = kwargs.get("json") or c._session.post.call_args[0][1]
        if payload is None:
            # positional
            payload = c._session.post.call_args[0][1]
        assert payload["method"] == "click"
        assert payload["params"] == [100, 200]

    def test_no_match_neither_session_called(self):
        """When condition doesn't match, no RPC is fired at all."""
        c, ctx = self._make_ctx()
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "NonExistentElement")
        entry.click()

        ctx._rpc_dedicated = Mock()
        ctx._check_and_fire(root, entry)

        ctx._rpc_dedicated.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Bug 4: /ui_elements uses parse_xml, not stdlib ET
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeviceUiParseXml:
    """/ui_elements must use parse_xml() + XML_PARSE_ERRORS, not ET.fromstring()."""

    def test_no_stdlib_et_import_in_device_ui(self):
        """device_ui.py must not import xml.etree.ElementTree directly."""
        import importlib
        import sys

        # Reload to get fresh module state (in case it was cached)
        mod_name = "api.routes.device_control.device_ui"
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
        else:
            mod = importlib.import_module(mod_name)

        # The module should NOT have ET as a module-level name
        assert not hasattr(mod, "ET"), (
            "device_ui.py still imports xml.etree.ElementTree as ET"
        )

    def test_parse_xml_imported(self):
        """device_ui module imports parse_xml from runtime.xml_utils."""
        import importlib
        import sys
        mod_name = "api.routes.device_control.device_ui"
        mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
        assert hasattr(mod, "parse_xml"), "parse_xml not imported in device_ui"

    def test_xml_parse_errors_imported(self):
        import importlib
        import sys
        mod_name = "api.routes.device_control.device_ui"
        mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
        assert hasattr(mod, "XML_PARSE_ERRORS"), "XML_PARSE_ERRORS not imported in device_ui"

    @pytest.mark.anyio
    async def test_invalid_xml_returns_500(self):
        """XML_PARSE_ERRORS caught by route → returns 500 with parse error message.

        lxml uses recover=True and never raises on malformed input, so we force
        parse_xml to raise by patching it — this tests the error-handling path.
        """
        from httpx import AsyncClient, ASGITransport
        from fastapi import FastAPI
        from runtime.core import DeviceManager
        from api.routes.device_control.device_ui import build_device_ui_router
        from runtime.xml_utils import XML_PARSE_ERRORS

        app = FastAPI()
        manager = MagicMock(spec=DeviceManager)
        mock_device = MagicMock()
        mock_device.hierarchy_xml.return_value = "<hierarchy/>"  # non-empty so route proceeds
        manager.get_device.return_value = mock_device

        # Raise the first error type from XML_PARSE_ERRORS to simulate a parse failure
        parse_exc = XML_PARSE_ERRORS[0]("forced parse error")

        app.include_router(build_device_ui_router(manager), prefix="/api")
        with patch("api.routes.device_control.device_ui.parse_xml", side_effect=parse_exc):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/devices/test-serial/ui_elements")

        assert resp.status_code == 500
        assert "parse" in resp.json().get("error", "").lower()

    @pytest.mark.anyio
    async def test_valid_xml_returns_elements(self):
        """Valid XML hierarchy is parsed and elements returned."""
        from httpx import AsyncClient, ASGITransport
        from fastapi import FastAPI
        from runtime.core import DeviceManager
        from api.routes.device_control.device_ui import build_device_ui_router

        app = FastAPI()
        manager = MagicMock(spec=DeviceManager)
        mock_device = MagicMock()
        mock_device.hierarchy_xml.return_value = SIMPLE_XML
        manager.get_device.return_value = mock_device

        app.include_router(build_device_ui_router(manager), prefix="/api")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/devices/test-serial/ui_elements")

        assert resp.status_code == 200
        data = resp.json()
        assert data["element_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Bug 5: _best_selector returns native "description" selector for content-desc
# ═══════════════════════════════════════════════════════════════════════════════

class TestBestSelector:
    """_best_selector must return native selector types, not xpath for content-desc."""

    @staticmethod
    def _sel(text="", rid="", desc=""):
        from api.routes.device_control.device_ui import _best_selector
        return _best_selector(text, rid, desc)

    def test_desc_only_returns_description_not_xpath(self):
        by, val = self._sel(desc="Home button")
        assert by == "description", f"Expected 'description', got {by!r}"
        assert val == "Home button"

    def test_desc_returns_exact_value_no_escaping(self):
        """Value must be the raw string, not an XPath expression."""
        by, val = self._sel(desc='Say "hello"')
        assert by == "description"
        assert val == 'Say "hello"'
        assert "//*" not in val, "Should not embed XPath in value"

    def test_text_wins_over_description(self):
        """Short text always takes priority over description."""
        by, val = self._sel(text="Login", desc="Login button")
        assert by == "text"
        assert val == "Login"

    def test_rid_with_slash_wins_over_description(self):
        """resource-id with package prefix wins over description."""
        by, val = self._sel(rid="com.app:id/btn", desc="Button")
        assert by == "resource-id"
        assert val == "com.app:id/btn"

    def test_desc_long_falls_through_to_rid(self):
        """Description ≥ 80 chars falls through; bare resource-id used instead."""
        long_desc = "x" * 80
        by, val = self._sel(rid="com.app:id/btn", desc=long_desc)
        assert by == "resource-id"
        assert val == "com.app:id/btn"

    def test_desc_long_no_rid_returns_none(self):
        """Description ≥ 80 chars with no other fallback → (None, None)."""
        long_desc = "x" * 80
        by, val = self._sel(desc=long_desc)
        assert by is None
        assert val is None

    def test_no_info_returns_none(self):
        by, val = self._sel()
        assert by is None
        assert val is None

    def test_text_long_skipped(self):
        """Text ≥ 80 chars falls through to next selector."""
        long_text = "t" * 80
        by, val = self._sel(text=long_text, rid="com.app:id/btn")
        assert by == "resource-id"

    def test_rid_without_slash_used_last(self):
        """resource-id without '/' (no package prefix) is used as last resort."""
        by, val = self._sel(rid="btn_id")
        assert by == "resource-id"
        assert val == "btn_id"

    def test_no_xpath_strings_ever_returned(self):
        """No combination of inputs should produce a selector_by of 'xpath'."""
        cases = [
            ("", "", "Close"),
            ("", "", 'Say "hi"'),
            ("", "btn_id", "Home"),
            ("Login", "com.app:id/x", "Login button"),
        ]
        for text, rid, desc in cases:
            by, _ = self._sel(text=text, rid=rid, desc=desc)
            assert by != "xpath", (
                f"_best_selector({text!r}, {rid!r}, {desc!r}) returned 'xpath' — should be native"
            )
