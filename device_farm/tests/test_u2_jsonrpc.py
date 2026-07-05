"""
tests/test_u2_jsonrpc.py — unit tests for U2JsonRpcClient and helpers.

All HTTP calls are mocked via unittest.mock — no real device needed.
Run: pytest tests/test_u2_jsonrpc.py -v
"""
from __future__ import annotations

import json
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, call, patch

from runtime.xml_utils import XML_PARSE_ERRORS, parse_xml

try:
    from lxml import etree as _ET
except ImportError:
    import xml.etree.ElementTree as _ET

from runtime.transports.u2_jsonrpc import (
    U2BatchError,
    U2JsonRpcClient,
    _BatchRelaySession,
    _WatcherBuilder,
    _WatcherContext,
    _WatcherEntry,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_response(result=None, error=None, status_code=200):
    """Build a fake requests.Response for _rpc()."""
    resp = Mock()
    resp.ok = status_code < 400
    resp.status_code = status_code
    body: dict = {"jsonrpc": "2.0", "id": 1}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    resp.text = json.dumps(body)
    return resp


def _make_client(host="127.0.0.1", port=9008, timeout=5.0, adb_shell=None):
    return U2JsonRpcClient(host=host, port=port, timeout=timeout, adb_shell=adb_shell)


SIMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="Home" resource-id="com.example:id/home"
        class="android.widget.TextView" package="com.example"
        content-desc="Home button" bounds="[0,0][100,50]"
        checkable="false" checked="false" clickable="true" enabled="true"
        focusable="true" focused="false" scrollable="false" selected="false"/>
  <node index="1" text="Settings" resource-id="com.example:id/settings"
        class="android.widget.Button" package="com.example"
        content-desc="" bounds="[100,0][200,50]"
        checkable="false" checked="false" clickable="true" enabled="true"
        focusable="true" focused="false" scrollable="false" selected="false"/>
</hierarchy>"""


class TestBatchRelaySession(unittest.TestCase):

    def test_batch_error_preserves_partial_results(self):
        class _Future:
            def result(self, timeout=None):
                return {
                    "ok": False,
                    "stopped_at": 1,
                    "results": [
                        {"op": "click", "ok": True},
                        {"op": "click", "ok": False, "error": "tap failed"},
                    ],
                    "error": "tap failed",
                }

        class _Loop:
            pass

        class _Manager:
            def u2_batch(self, serial, actions, timeout=30.0):
                return {}

        with patch("asyncio.run_coroutine_threadsafe", return_value=_Future()):
            session = _BatchRelaySession(_Manager(), "SN001", _Loop())
            with self.assertRaises(U2BatchError) as ctx:
                session.batch([{"op": "click"}, {"op": "click"}], timeout=3.0)

        self.assertEqual(str(ctx.exception), "tap failed")
        self.assertEqual(ctx.exception.stopped_at, 1)
        self.assertEqual(ctx.exception.results[0]["ok"], True)
        self.assertEqual(ctx.exception.results[1]["error"], "tap failed")


# ═══════════════════════════════════════════════════════════════════════════════
# _WatcherEntry
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherEntry(unittest.TestCase):

    def test_initial_action_is_none(self):
        e = _WatcherEntry("test", "text", "OK")
        self.assertIsNone(e._action)

    def test_click_sets_action(self):
        e = _WatcherEntry("test", "text", "OK")
        ret = e.click()
        self.assertEqual(e._action, ("click",))
        self.assertIs(ret, e)  # fluent

    def test_press_sets_action(self):
        e = _WatcherEntry("test", "text", "OK")
        ret = e.press("back")
        self.assertEqual(e._action, ("press", "back"))
        self.assertIs(ret, e)


# ═══════════════════════════════════════════════════════════════════════════════
# _WatcherBuilder
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherBuilder(unittest.TestCase):

    def setUp(self):
        client = _make_client()
        self.ctx = client.watchers

    def _builder(self, name="w1"):
        return _WatcherBuilder(self.ctx, name)

    def test_when_text(self):
        e = self._builder().when(text="Wait")
        self.assertEqual(e.by, "text")
        self.assertEqual(e.value, "Wait")

    def test_when_textContains(self):
        e = self._builder().when(textContains="stopped")
        self.assertEqual(e.by, "textContains")

    def test_when_textStartsWith(self):
        e = self._builder().when(textStartsWith="Error")
        self.assertEqual(e.by, "textStartsWith")

    def test_when_resourceId(self):
        e = self._builder().when(resourceId="com.app:id/btn")
        self.assertEqual(e.by, "resource-id")

    def test_when_description(self):
        e = self._builder().when(description="Close")
        self.assertEqual(e.by, "description")

    def test_when_className(self):
        e = self._builder().when(className="android.widget.Button")
        self.assertEqual(e.by, "className")

    def test_when_no_args_raises(self):
        with self.assertRaises(ValueError):
            self._builder().when()

    def test_when_registers_entry_in_context(self):
        self._builder("my_watcher").when(text="OK").click()
        self.assertIn("my_watcher", self.ctx._entries)

    def test_when_overwrites_existing(self):
        b = _WatcherBuilder(self.ctx, "same")
        b.when(text="First").click()
        b.when(text="Second").press("back")
        e = self.ctx._entries["same"]
        self.assertEqual(e.value, "Second")
        self.assertEqual(e._action, ("press", "back"))


# ═══════════════════════════════════════════════════════════════════════════════
# _WatcherContext._node_matches
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherNodeMatches(unittest.TestCase):

    def _node(self, **attrs):
        el = _ET.Element("node")
        for k, v in attrs.items():
            el.set(k, v)
        return el

    def test_text_exact(self):
        node = self._node(text="Home")
        self.assertTrue(_WatcherContext._node_matches(node, "text", "Home"))
        self.assertFalse(_WatcherContext._node_matches(node, "text", "home"))

    def test_textContains(self):
        node = self._node(text="Settings screen")
        self.assertTrue(_WatcherContext._node_matches(node, "textContains", "Settings"))
        self.assertFalse(_WatcherContext._node_matches(node, "textContains", "Profile"))

    def test_textStartsWith(self):
        node = self._node(text="Error: invalid")
        self.assertTrue(_WatcherContext._node_matches(node, "textStartsWith", "Error"))
        self.assertFalse(_WatcherContext._node_matches(node, "textStartsWith", "Warning"))

    def test_resource_id(self):
        node = self._node(**{"resource-id": "com.app:id/btn"})
        self.assertTrue(_WatcherContext._node_matches(node, "resource-id", "com.app:id/btn"))
        self.assertTrue(_WatcherContext._node_matches(node, "id", "com.app:id/btn"))

    def test_className(self):
        node = self._node(**{"class": "android.widget.Button"})
        self.assertTrue(_WatcherContext._node_matches(node, "className", "android.widget.Button"))
        self.assertTrue(_WatcherContext._node_matches(node, "class name", "android.widget.Button"))

    def test_description(self):
        node = self._node(**{"content-desc": "Close dialog"})
        self.assertTrue(_WatcherContext._node_matches(node, "description", "Close dialog"))
        self.assertTrue(_WatcherContext._node_matches(node, "content-desc", "Close dialog"))
        self.assertTrue(_WatcherContext._node_matches(node, "accessibility id", "Close dialog"))

    def test_package(self):
        node = self._node(package="com.android.systemui")
        self.assertTrue(_WatcherContext._node_matches(node, "package", "com.android.systemui"))

    def test_unknown_by_returns_false(self):
        node = self._node(text="something")
        self.assertFalse(_WatcherContext._node_matches(node, "unknown_by", "something"))

    def test_missing_attribute_returns_false(self):
        node = _ET.Element("node")  # no attributes
        self.assertFalse(_WatcherContext._node_matches(node, "text", "anything"))


# ═══════════════════════════════════════════════════════════════════════════════
# _WatcherContext._bounds_from_node
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherBoundsFromNode(unittest.TestCase):

    def test_valid_bounds(self):
        node = _ET.Element("node")
        node.set("bounds", "[10,20][110,70]")
        b = _WatcherContext._bounds_from_node(node)
        self.assertEqual(b, {"left": 10, "top": 20, "right": 110, "bottom": 70})

    def test_missing_bounds_returns_none(self):
        node = _ET.Element("node")
        self.assertIsNone(_WatcherContext._bounds_from_node(node))

    def test_malformed_bounds_returns_none(self):
        node = _ET.Element("node")
        node.set("bounds", "invalid")
        self.assertIsNone(_WatcherContext._bounds_from_node(node))

    def test_negative_bounds(self):
        node = _ET.Element("node")
        node.set("bounds", "[-10,-20][100,50]")
        b = _WatcherContext._bounds_from_node(node)
        self.assertEqual(b["left"], -10)
        self.assertEqual(b["top"], -20)


# ═══════════════════════════════════════════════════════════════════════════════
# _WatcherContext — fire logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherFire(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()
        self.ctx = self.client.watchers

    def test_check_and_fire_click(self):
        """Watcher fires click via dedicated session at center of matched node bounds."""
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        entry.click()
        # Since fix #3, _check_and_fire uses _rpc_dedicated, not client.click
        self.ctx._rpc_dedicated = Mock(return_value=None)
        self.client.click = Mock()  # must NOT be called
        self.ctx._check_and_fire(root, entry)
        self.client.click.assert_not_called()
        self.ctx._rpc_dedicated.assert_called_once_with("click", 50, 25)  # center of [0,0][100,50]

    def test_check_and_fire_press(self):
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        entry.press("back")
        # Since fix #3, _check_and_fire uses _rpc_dedicated, not client.press
        self.ctx._rpc_dedicated = Mock(return_value=None)
        self.client.press = Mock()  # must NOT be called
        self.ctx._check_and_fire(root, entry)
        self.client.press.assert_not_called()
        self.ctx._rpc_dedicated.assert_called()

    def test_check_and_fire_no_match(self):
        """No match → neither click nor press called."""
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "NonExistent")
        entry.click()
        self.client.click = Mock()
        self.ctx._check_and_fire(root, entry)
        self.client.click.assert_not_called()

    def test_run_once_skips_entry_without_action(self):
        self.ctx._fetch_page_source = Mock(return_value=SIMPLE_XML)
        entry = _WatcherEntry("w", "text", "Home")
        # No .click() or .press() called → _action is None
        self.ctx._entries["w"] = entry
        self.client.click = Mock()
        self.ctx._run_once()
        self.client.click.assert_not_called()

    def test_run_once_empty_page_source(self):
        """Empty page_source → run_once returns early without crash."""
        self.ctx._fetch_page_source = Mock(return_value="")
        self.ctx._entries["w"] = _WatcherEntry("w", "text", "OK")
        self.ctx._entries["w"].click()
        self.client.click = Mock()
        self.ctx._run_once()
        self.client.click.assert_not_called()

    def test_run_once_invalid_xml(self):
        """Malformed XML → run_once returns early without crash."""
        self.ctx._fetch_page_source = Mock(return_value="<broken>")
        self.ctx._entries["w"] = _WatcherEntry("w", "text", "OK")
        self.ctx._entries["w"].click()
        self.client.click = Mock()
        # Should not raise
        self.ctx._run_once()

    def test_find_node_xpath(self):
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "xpath", '//*[@text="Home"]')
        node = self.ctx._find_node(root, entry)
        self.assertIsNotNone(node)
        self.assertEqual(node.get("text"), "Home")

    def test_find_node_xpath_no_match(self):
        root = parse_xml(SIMPLE_XML)
        entry = _WatcherEntry("w", "xpath", '//*[@text="Missing"]')
        self.assertIsNone(self.ctx._find_node(root, entry))


# ═══════════════════════════════════════════════════════════════════════════════
# _WatcherContext — lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherLifecycle(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()
        self.ctx = self.client.watchers

    def test_start_creates_daemon_thread(self):
        self.ctx._run_once = Mock()  # prevent real HTTP calls
        self.ctx.start(interval=100.0)
        self.assertTrue(self.ctx._running)
        self.assertIsNotNone(self.ctx._thread)
        self.assertTrue(self.ctx._thread.daemon)
        self.ctx.stop()

    def test_start_idempotent(self):
        self.ctx._run_once = Mock()
        self.ctx.start()
        t1 = self.ctx._thread
        self.ctx.start()  # second call — should be no-op
        self.assertIs(self.ctx._thread, t1)
        self.ctx.stop()

    def test_stop_sets_running_false(self):
        self.ctx._run_once = Mock()
        self.ctx.start()
        self.ctx.stop()
        self.assertFalse(self.ctx._running)

    def test_remove_entry(self):
        self.ctx._entries["w"] = _WatcherEntry("w", "text", "OK")
        self.ctx.remove("w")
        self.assertNotIn("w", self.ctx._entries)

    def test_reset_clears_all(self):
        self.ctx._entries["a"] = _WatcherEntry("a", "text", "A")
        self.ctx._entries["b"] = _WatcherEntry("b", "text", "B")
        self.ctx.reset()
        self.assertEqual(len(self.ctx), 0)

    def test_getitem(self):
        e = _WatcherEntry("w", "text", "OK")
        self.ctx._entries["w"] = e
        self.assertIs(self.ctx["w"], e)

    def test_len(self):
        self.ctx._entries["a"] = _WatcherEntry("a", "text", "A")
        self.ctx._entries["b"] = _WatcherEntry("b", "text", "B")
        self.assertEqual(len(self.ctx), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — init / connection
# ═══════════════════════════════════════════════════════════════════════════════

class TestClientInit(unittest.TestCase):

    def test_base_url(self):
        c = _make_client(host="192.168.1.5", port=9008)
        self.assertEqual(c._base, "http://192.168.1.5:9008")

    def test_touch_timeout_capped(self):
        c = _make_client(timeout=20.0)
        self.assertEqual(c._touch_timeout, 3.0)

    def test_touch_timeout_below_cap(self):
        c = _make_client(timeout=2.0)
        self.assertEqual(c._touch_timeout, 2.0)

    def test_gzip_disabled(self):
        c = _make_client()
        self.assertEqual(c._session.headers.get("Accept-Encoding"), "")

    def test_watchers_created(self):
        c = _make_client()
        self.assertIsInstance(c.watchers, _WatcherContext)

    def test_adb_shell_stored(self):
        shell = Mock()
        c = _make_client(adb_shell=shell)
        self.assertIs(c._adb_shell, shell)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — _rpc()
# ═══════════════════════════════════════════════════════════════════════════════

class TestRpc(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def _mock_post(self, result=None, error=None, status=200):
        self.client._session.post = Mock(
            return_value=_make_response(result=result, error=error, status_code=status)
        )

    def test_success_returns_result(self):
        self._mock_post(result={"currentPackageName": "com.app"})
        r = self.client._rpc("deviceInfo")
        self.assertEqual(r["currentPackageName"], "com.app")

    def test_increments_req_id(self):
        self._mock_post(result=True)
        self.client._rpc("ping")
        self.client._rpc("ping")
        self.assertEqual(self.client._req_id, 2)

    def test_http_error_raises_runtime_error(self):
        self._mock_post(status=500)
        with self.assertRaises(RuntimeError) as cm:
            self.client._rpc("something")
        self.assertIn("JSON-RPC HTTP 500", str(cm.exception))

    def test_empty_response_raises(self):
        resp = Mock()
        resp.ok = True
        resp.status_code = 200
        resp.text = "   "
        self.client._session.post = Mock(return_value=resp)
        with self.assertRaises(RuntimeError) as cm:
            self.client._rpc("something")
        self.assertIn("empty response", str(cm.exception))

    def test_invalid_json_raises(self):
        resp = Mock()
        resp.ok = True
        resp.status_code = 200
        resp.text = "not-json"
        self.client._session.post = Mock(return_value=resp)
        with self.assertRaises(RuntimeError) as cm:
            self.client._rpc("something")
        self.assertIn("invalid response", str(cm.exception))

    def test_jsonrpc_error_raises(self):
        self._mock_post(error={"code": -32001, "message": "UiObjectNotFoundException"})
        with self.assertRaises(RuntimeError) as cm:
            self.client._rpc("objInfo", {})
        self.assertIn("JSON-RPC error", str(cm.exception))

    def test_positional_args_sent_as_list(self):
        self._mock_post(result=True)
        self.client._rpc("click", 100, 200)
        payload = self.client._session.post.call_args[1]["json"]
        self.assertEqual(payload["params"], [100, 200])

    def test_kwargs_sent_as_dict(self):
        self._mock_post(result=True)
        self.client._rpc("someMethod", key="value")
        payload = self.client._session.post.call_args[1]["json"]
        self.assertEqual(payload["params"], {"key": "value"})

    def test_custom_timeout_used(self):
        self._mock_post(result=True)
        self.client._rpc("click", 1, 2, _timeout=99.0)
        kwargs = self.client._session.post.call_args[1]
        self.assertEqual(kwargs["timeout"], 99.0)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — _build_selector
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildSelector(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_text(self):
        s = self.client._build_selector("text", "Login")
        self.assertEqual(s["text"], "Login")
        self.assertEqual(s["mask"], 0x01)

    def test_resource_id(self):
        s = self.client._build_selector("resource-id", "com.app:id/btn")
        self.assertEqual(s["resourceId"], "com.app:id/btn")
        self.assertEqual(s["mask"], 0x200000)

    def test_id_alias(self):
        s = self.client._build_selector("id", "com.app:id/btn")
        self.assertEqual(s["resourceId"], "com.app:id/btn")

    def test_className(self):
        s = self.client._build_selector("className", "android.widget.Button")
        self.assertEqual(s["className"], "android.widget.Button")
        self.assertEqual(s["mask"], 0x10)

    def test_description(self):
        s = self.client._build_selector("description", "Back")
        self.assertEqual(s["description"], "Back")
        self.assertEqual(s["mask"], 0x40)

    def test_descriptionContains(self):
        s = self.client._build_selector("descriptionContains", "Back")
        self.assertEqual(s["descriptionContains"], "Back")
        self.assertEqual(s["mask"], 0x80)

    def test_descriptionStartsWith(self):
        s = self.client._build_selector("descriptionStartsWith", "Back")
        self.assertEqual(s["descriptionStartsWith"], "Back")
        self.assertEqual(s["mask"], 0x200)

    def test_descriptionStartswith_legacy_case(self):
        s = self.client._build_selector("descriptionStartswith", "Back")
        self.assertEqual(s["descriptionStartsWith"], "Back")
        self.assertEqual(s["mask"], 0x200)

    def test_accessibility_id_alias(self):
        s = self.client._build_selector("accessibility id", "Back")
        self.assertEqual(s["description"], "Back")

    def test_textContains(self):
        s = self.client._build_selector("textContains", "Login")
        self.assertEqual(s["textContains"], "Login")
        self.assertEqual(s["mask"], 0x02)

    def test_textStartsWith(self):
        s = self.client._build_selector("textStartsWith", "Log")
        self.assertEqual(s["textStartsWith"], "Log")
        self.assertEqual(s["mask"], 0x08)

    def test_package(self):
        s = self.client._build_selector("package", "com.app")
        self.assertEqual(s["packageName"], "com.app")
        self.assertEqual(s["mask"], 0x80000)

    def test_unknown_falls_back_to_text(self):
        s = self.client._build_selector("unknown_type", "value")
        self.assertEqual(s["text"], "value")
        self.assertEqual(s["mask"], 0x01)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — _parse_bounds
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseBounds(unittest.TestCase):

    def test_dict_passthrough(self):
        d = {"left": 0, "top": 10, "right": 100, "bottom": 50}
        self.assertEqual(U2JsonRpcClient._parse_bounds(d), d)

    def test_android_string_format(self):
        b = U2JsonRpcClient._parse_bounds("[10,20][110,70]")
        self.assertEqual(b, {"left": 10, "top": 20, "right": 110, "bottom": 70})

    def test_negative_coords(self):
        b = U2JsonRpcClient._parse_bounds("[-5,-10][100,50]")
        self.assertEqual(b["left"], -5)
        self.assertEqual(b["top"], -10)

    def test_invalid_string_returns_none(self):
        self.assertIsNone(U2JsonRpcClient._parse_bounds("invalid"))

    def test_none_returns_none(self):
        self.assertIsNone(U2JsonRpcClient._parse_bounds(None))

    def test_too_few_numbers_returns_none(self):
        self.assertIsNone(U2JsonRpcClient._parse_bounds("[0,0][100]"))


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — _normalize_et_xpath
# ═══════════════════════════════════════════════════════════════════════════════

class TestNormalizeXpath(unittest.TestCase):

    def test_double_slash_prefix(self):
        self.assertEqual(U2JsonRpcClient._normalize_et_xpath("//*[@text='OK']"),
                         ".//*[@text='OK']")

    def test_single_slash_prefix(self):
        self.assertEqual(U2JsonRpcClient._normalize_et_xpath("/hierarchy/node"),
                         "./hierarchy/node")

    def test_relative_unchanged(self):
        self.assertEqual(U2JsonRpcClient._normalize_et_xpath("node[@text='OK']"),
                         "node[@text='OK']")

    def test_empty_string(self):
        self.assertEqual(U2JsonRpcClient._normalize_et_xpath(""), "")

    def test_strips_whitespace(self):
        self.assertEqual(U2JsonRpcClient._normalize_et_xpath("  //*[@id='x']  "),
                         ".//*[@id='x']")


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — ping / verify
# ═══════════════════════════════════════════════════════════════════════════════

class TestPingVerify(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_ping_success(self):
        resp = Mock(status_code=200)
        self.client._session.get = Mock(return_value=resp)
        self.assertTrue(self.client.ping())

    def test_ping_non_200(self):
        resp = Mock(status_code=404)
        self.client._session.get = Mock(return_value=resp)
        self.assertFalse(self.client.ping())

    def test_ping_exception(self):
        self.client._session.get = Mock(side_effect=ConnectionError())
        self.assertFalse(self.client.ping())

    def test_verify_success(self):
        self.client._rpc = Mock(return_value={"currentPackageName": "com.app"})
        result = self.client.verify()
        self.assertEqual(result["currentPackageName"], "com.app")

    def test_verify_unexpected_response_raises(self):
        self.client._rpc = Mock(return_value={"unexpectedKey": "value"})
        with self.assertRaises(RuntimeError):
            self.client.verify()

    def test_verify_none_raises(self):
        self.client._rpc = Mock(return_value=None)
        with self.assertRaises(RuntimeError):
            self.client.verify()


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — find_element
# ═══════════════════════════════════════════════════════════════════════════════

class TestFindElement(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_instant_check_found(self):
        self.client._rpc = Mock(return_value={"text": "OK", "bounds": {}})
        eid = self.client.find_element("text", "OK", timeout=0)
        self.assertEqual(eid, "text::OK")

    def test_instant_check_not_found(self):
        self.client._rpc = Mock(side_effect=RuntimeError("JSON-RPC error: UiObjectNotFound"))
        eid = self.client.find_element("text", "Missing", timeout=0)
        self.assertIsNone(eid)

    def test_instant_check_connection_error_raises(self):
        self.client._rpc = Mock(side_effect=RuntimeError("connection refused"))
        with self.assertRaises(RuntimeError):
            self.client.find_element("text", "OK", timeout=0)

    def test_wait_found(self):
        self.client._rpc = Mock(return_value=True)
        eid = self.client.find_element("text", "OK", timeout=5.0)
        self.assertEqual(eid, "text::OK")
        args = self.client._rpc.call_args[0]
        self.assertEqual(args[0], "waitForExists")
        self.assertEqual(args[2], 5000)  # timeout in ms

    def test_wait_not_found(self):
        self.client._rpc = Mock(return_value=False)
        eid = self.client.find_element("text", "Missing", timeout=5.0)
        self.assertIsNone(eid)

    def test_xpath_delegates(self):
        self.client._find_element_xpath = Mock(return_value="xpath::expr")
        eid = self.client.find_element("xpath", "//node", timeout=5.0)
        self.assertEqual(eid, "xpath::expr")
        self.client._find_element_xpath.assert_called_once_with("//node", 5.0)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — find_element_with_bounds
# ═══════════════════════════════════════════════════════════════════════════════

class TestFindElementWithBounds(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_success_dict_bounds(self):
        self.client._rpc = Mock(return_value={
            "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 50}
        })
        r = self.client.find_element_with_bounds("text", "OK")
        self.assertIsNotNone(r)
        self.assertEqual(r["bounds"]["right"], 100)
        self.assertEqual(r["eid"], "text::OK")

    def test_success_string_bounds(self):
        self.client._rpc = Mock(return_value={"bounds": "[0,0][100,50]"})
        r = self.client.find_element_with_bounds("text", "OK")
        self.assertEqual(r["bounds"]["right"], 100)

    def test_not_found_returns_none(self):
        self.client._rpc = Mock(
            side_effect=RuntimeError("JSON-RPC error: UiObjectNotFoundException"))
        r = self.client.find_element_with_bounds("text", "Missing")
        self.assertIsNone(r)

    def test_xpath_delegates(self):
        self.client._find_element_xpath_with_bounds = Mock(
            return_value={"eid": "xpath::expr", "bounds": None})
        r = self.client.find_element_with_bounds("xpath", "//node")
        self.assertIsNotNone(r)

    def test_xpath_with_bounds_uses_caller_timeout(self):
        client = _make_client(timeout=20.0)
        captured = []

        def fake_page_source(timeout=None, compressed=False):
            captured.append(timeout)
            return SIMPLE_XML

        client.page_source = fake_page_source
        result = client._find_element_xpath_with_bounds('//*[@text="Home"]', timeout=0.25)

        self.assertIsNotNone(result)
        self.assertEqual(result["bounds"]["right"], 100)
        self.assertTrue(captured)
        self.assertLess(captured[0], 2.0)

    def test_spec_with_bounds_uses_instant_obj_info_first(self):
        from services.scenario_selector import ScenarioSelectorSpec

        client = _make_client(timeout=20.0)
        client._rpc = Mock(return_value={"bounds": "[0,0][100,50]"})

        result = client.find_element_with_bounds_spec(
            ScenarioSelectorSpec(by="resource-id", value="com.app:id/login"),
            timeout=0.5,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["eid"], "resource-id::com.app:id/login")
        self.assertEqual(result["bounds"]["right"], 100)
        self.assertEqual(client._rpc.call_count, 1)
        self.assertEqual(client._rpc.call_args[0][0], "objInfo")


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — page_source
# ═══════════════════════════════════════════════════════════════════════════════

class TestPageSource(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_success_returns_xml(self):
        self.client._rpc = Mock(return_value=SIMPLE_XML)
        xml = self.client.page_source()
        self.assertIn("<hierarchy", xml)

    def test_empty_stub_retries_and_returns_empty(self):
        self.client._rpc = Mock(return_value='<hierarchy rotation="0" />')
        with patch("time.sleep"):  # don't actually sleep
            xml = self.client.page_source()
        self.assertEqual(xml, "")
        self.assertEqual(self.client._rpc.call_count, 3)

    def test_http_error_retries(self):
        self.client._rpc = Mock(
            side_effect=RuntimeError("JSON-RPC HTTP 500 for method='dumpWindowHierarchy': ''"))
        with patch("time.sleep"):
            xml = self.client.page_source()
        self.assertEqual(xml, "")
        self.assertEqual(self.client._rpc.call_count, 3)

    def test_connection_error_propagates(self):
        self.client._rpc = Mock(side_effect=RuntimeError("connection reset"))
        with self.assertRaises(RuntimeError):
            self.client.page_source()

    def test_empty_string_retries(self):
        self.client._rpc = Mock(return_value="")
        with patch("time.sleep"):
            xml = self.client.page_source()
        self.assertEqual(xml, "")
        self.assertEqual(self.client._rpc.call_count, 3)

    def test_recovers_on_second_attempt(self):
        self.client._rpc = Mock(side_effect=[
            RuntimeError("JSON-RPC HTTP 500 for method='dumpWindowHierarchy': ''"),
            SIMPLE_XML,
        ])
        with patch("time.sleep"):
            xml = self.client.page_source()
        self.assertIn("<hierarchy", xml)

    def test_compressed_uses_dump_window_hierarchy2(self):
        self.client._rpc = Mock(return_value=SIMPLE_XML)

        xml = self.client.page_source(compressed=True)

        self.assertIn("<hierarchy", xml)
        self.client._rpc.assert_called_once()
        method, options = self.client._rpc.call_args[0][:2]
        self.assertEqual(method, "dumpWindowHierarchy2")
        self.assertEqual(options["compressed"], True)
        self.assertEqual(options["waitForIdleMs"], 0)
        self.assertEqual(options["trimFalseAttributes"], True)

    def test_compressed_falls_back_when_dump_window_hierarchy2_missing(self):
        self.client._rpc = Mock(side_effect=[
            RuntimeError("JSON-RPC error for method='dumpWindowHierarchy2': Method not found"),
            SIMPLE_XML,
        ])

        xml = self.client.page_source(compressed=True)

        self.assertIn("<hierarchy", xml)
        self.assertEqual(self.client._rpc.call_count, 2)
        self.assertEqual(self.client._rpc.call_args_list[0][0][0], "dumpWindowHierarchy2")
        self.assertEqual(self.client._rpc.call_args_list[1][0][0], "dumpWindowHierarchy")
        self.assertIs(self.client._dump_hierarchy2_supported, False)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — gestures
# ═══════════════════════════════════════════════════════════════════════════════

class TestGestures(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()
        self.client._rpc = Mock(return_value=None)

    def test_click_calls_rpc(self):
        self.client.click(100, 200)
        self.client._rpc.assert_called_once_with("click", 100, 200,
                                                  _timeout=self.client._touch_timeout)

    def test_swipe_calls_rpc_with_steps(self):
        self.client.swipe(0, 500, 0, 100, duration=0.5)
        args = self.client._rpc.call_args[0]
        self.assertEqual(args[0], "swipe")
        self.assertEqual(args[5], 20)  # steps = 0.5 * 40

    def test_drag_calls_rpc(self):
        self.client.drag(0, 500, 0, 100, duration=0.5)
        args = self.client._rpc.call_args[0]
        self.assertEqual(args[0], "drag")
        self.assertEqual(args[5], 10)

    def test_long_click_calls_rpc(self):
        self.client.long_click(100, 200, duration=0.8)
        args = self.client._rpc.call_args[0]
        self.assertEqual(args[0], "longClick")


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — press (cache logic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPress(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_empty_key_is_noop(self):
        self.client._rpc = Mock()
        self.client.press("")
        self.client._rpc.assert_not_called()

    def test_caches_working_method(self):
        call_count = [0]
        def rpc(method, *args, **kw):
            call_count[0] += 1
            if method == "pressKey":
                return True
            raise RuntimeError("not supported")
        self.client._rpc = rpc

        self.client.press("home")
        self.client.press("back")
        # Second call should use cached method — no probing
        self.assertIsNotNone(self.client._press_method)

    def test_falls_back_to_keycode(self):
        def rpc(method, *args, **kw):
            if method in ("pressKey", "press", "key", "keyevent"):
                raise RuntimeError("unsupported")
            if method == "pressKeyCode":
                return True
            raise RuntimeError("unsupported")
        self.client._rpc = rpc
        # Should not raise
        self.client.press("home")
        self.assertEqual(self.client._press_keycode_method, "pressKeyCode")

    def test_unknown_key_raises(self):
        self.client._rpc = Mock(side_effect=RuntimeError("unsupported"))
        with self.assertRaises(RuntimeError):
            self.client.press("unknownkey12345")


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — __call__ (selector builder)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCallSelector(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_text(self):
        el = self.client(text="Login")
        self.assertEqual(el._by, "text")
        self.assertEqual(el._value, "Login")

    def test_resourceId(self):
        el = self.client(resourceId="com.app:id/btn")
        self.assertEqual(el._by, "resource-id")

    def test_description(self):
        el = self.client(description="Back")
        self.assertEqual(el._by, "description")

    def test_className(self):
        el = self.client(className="android.widget.Button")
        self.assertEqual(el._by, "className")

    def test_textContains(self):
        el = self.client(textContains="Login")
        self.assertEqual(el._by, "textContains")

    def test_textStartsWith(self):
        el = self.client(textStartsWith="Log")
        self.assertEqual(el._by, "textStartsWith")

    def test_package(self):
        el = self.client(package="com.app")
        self.assertEqual(el._by, "package")

    def test_no_kwargs_raises(self):
        with self.assertRaises(ValueError):
            self.client()

    def test_unknown_kwarg_raises(self):
        with self.assertRaises(ValueError):
            self.client(index=0)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — app_start / app_wait / session
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppLifecycle(unittest.TestCase):

    def setUp(self):
        self.shell = Mock(return_value="")
        self.client = _make_client(adb_shell=self.shell)
        self.client._rpc = Mock(return_value=None)

    def test_app_start_no_activity(self):
        self.client.app_start("com.example")
        cmd = self.shell.call_args[0][0]
        self.assertIn("am start", cmd)
        self.assertIn("com.example", cmd)
        self.assertIn("android.intent.action.MAIN", cmd)

    def test_app_start_with_activity(self):
        self.client.app_start("com.example", ".MainActivity")
        cmd = self.shell.call_args[0][0]
        self.assertIn("am start -n com.example/.MainActivity", cmd)

    def test_app_start_no_shell_raises(self):
        c = _make_client(adb_shell=None)
        with self.assertRaises(RuntimeError) as cm:
            c.app_start("com.example")
        self.assertIn("adb_shell", str(cm.exception))

    def test_app_stop_calls_rpc(self):
        self.client.app_stop("com.example")
        self.client._rpc.assert_called_once_with("stopPackage", "com.example")

    def test_app_wait_found(self):
        self.client._rpc = Mock(return_value={"currentPackageName": "com.example"})
        result = self.client.app_wait("com.example", timeout=5.0)
        self.assertTrue(result)

    def test_app_wait_timeout(self):
        self.client._rpc = Mock(return_value={"currentPackageName": "com.other"})
        with patch("time.sleep"):
            result = self.client.app_wait("com.example", timeout=0.01)
        self.assertFalse(result)

    def test_app_wait_front_param_accepted(self):
        self.client._rpc = Mock(return_value={"currentPackageName": "com.example"})
        # Both front=True and front=False should work
        self.assertTrue(self.client.app_wait("com.example", front=True, timeout=5.0))
        self.assertTrue(self.client.app_wait("com.example", front=False, timeout=5.0))

    def test_session_launches_and_stops(self):
        self.client.app_stop = Mock()
        self.client.app_start = Mock()
        self.client.app_wait = Mock(return_value=True)

        with self.client.session("com.example") as s:
            self.assertIs(s, self.client)
            self.client.app_start.assert_called_once()
            self.client.app_wait.assert_called_once()

        # app_stop called twice: before launch + on exit
        self.assertEqual(self.client.app_stop.call_count, 2)

    def test_session_stops_on_exception(self):
        self.client.app_stop = Mock()
        self.client.app_start = Mock()
        self.client.app_wait = Mock(return_value=True)

        with self.assertRaises(ValueError):
            with self.client.session("com.example"):
                raise ValueError("test error")

        self.assertEqual(self.client.app_stop.call_count, 2)

    def test_session_raises_if_app_not_foreground(self):
        self.client.app_stop = Mock()
        self.client.app_start = Mock()
        self.client.app_wait = Mock(return_value=False)

        with self.assertRaises(RuntimeError) as cm:
            with self.client.session("com.example", launch_timeout=1.0):
                pass
        self.assertIn("foreground", str(cm.exception))


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — element proxy (pinch / drag_to)
# ═══════════════════════════════════════════════════════════════════════════════

class TestElementProxy(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()
        self.client._rpc = Mock(return_value=None)

    def _element(self, by="text", value="OK"):
        return self.client(text=value) if by == "text" else self.client(resourceId=value)

    def test_drag_to_calls_objDrag(self):
        el = self._element()
        el.drag_to(540, 960, duration=0.5)
        args = self.client._rpc.call_args[0]
        self.assertEqual(args[0], "objDrag")
        self.assertEqual(args[2], 540)
        self.assertEqual(args[3], 960)

    def test_pinch_in_calls_rpc(self):
        el = self._element()
        el.pinch_in(percent=50, steps=10)
        args = self.client._rpc.call_args[0]
        self.assertEqual(args[0], "pinchIn")
        self.assertEqual(args[2], 50)
        self.assertEqual(args[3], 10)

    def test_pinch_out_calls_rpc(self):
        el = self._element()
        el.pinch_out(percent=75, steps=15)
        args = self.client._rpc.call_args[0]
        self.assertEqual(args[0], "pinchOut")
        self.assertEqual(args[2], 75)
        self.assertEqual(args[3], 15)

    def test_element_click_dispatches(self):
        self.client.find_element = Mock(return_value="text::OK")
        self.client.find_element_with_bounds = Mock(return_value={
            "eid": "text::OK",
            "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 50},
        })
        el = self._element()
        el.click()
        self.client._rpc.assert_called()

    def test_element_click_not_found_raises(self):
        self.client.find_element = Mock(return_value=None)
        el = self._element()
        with self.assertRaises(RuntimeError):
            el.click()

    def test_wait_delegates(self):
        self.client._wait_for_exists = Mock(return_value=True)
        el = self._element()
        result = el.wait(timeout=5.0)
        self.assertTrue(result)
        self.client._wait_for_exists.assert_called_once_with("text", "OK", 5.0)

    def test_wait_gone_delegates(self):
        self.client._wait_until_gone = Mock(return_value=True)
        el = self._element()
        result = el.wait_gone(timeout=3.0)
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — watcher() convenience method
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatcherConvenience(unittest.TestCase):

    def test_watcher_returns_builder(self):
        c = _make_client()
        b = c.watcher("test")
        self.assertIsInstance(b, _WatcherBuilder)

    def test_full_watcher_registration(self):
        c = _make_client()
        c.watcher("anr").when(text="Wait").click()
        self.assertIn("anr", c.watchers._entries)
        e = c.watchers._entries["anr"]
        self.assertEqual(e.by, "text")
        self.assertEqual(e.value, "Wait")
        self.assertEqual(e._action, ("click",))


# ═══════════════════════════════════════════════════════════════════════════════
# U2JsonRpcClient — send_keys / clear_text
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendKeys(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_send_keys_focused_element(self):
        """Uses setText on focused element when objInfo finds one."""
        call_log = []
        def rpc(method, *args, **kw):
            call_log.append(method)
            if method == "objInfo":
                return {"text": ""}  # element found
            return True
        self.client._rpc = rpc
        self.client.send_keys("hello")
        self.assertIn("objInfo", call_log)
        self.assertIn("setText", call_log)

    def test_send_keys_fallback_to_ime(self):
        """Falls back to setFastInputText when no focused element."""
        call_log = []
        def rpc(method, *args, **kw):
            call_log.append(method)
            if method == "objInfo":
                raise RuntimeError("JSON-RPC error: UiObjectNotFound")
            if method == "setFastInputText":
                return True
            raise RuntimeError("unsupported")
        self.client._rpc = rpc
        self.client.send_keys("hello")
        self.assertIn("setFastInputText", call_log)

    def test_send_keys_append_uses_adb_keyboard(self):
        """Live append uses AdbKeyboard IME broadcast (incremental typing)."""
        call_log = []
        def adb_shell(cmd: str) -> str:
            call_log.append(cmd)
            if "ADB_KEYBOARD_INPUT_TEXT" in cmd:
                return "Broadcast completed: result=-1"
            return ""
        self.client._adb_shell = adb_shell
        def rpc(method, *args, **kw):
            raise RuntimeError("no jsonrpc ime")
        self.client._rpc = rpc
        self.client.send_keys_append("việt")
        self.assertTrue(any("ime enable" in c for c in call_log))
        self.assertTrue(any("ADB_KEYBOARD_INPUT_TEXT" in c for c in call_log))
        self.assertNotIn("setText", [c for c in call_log])

    def test_set_text_focused(self):
        call_log = []
        def rpc(method, *args, **kw):
            call_log.append(method)
            if method == "objInfo":
                return {"text": "old"}
            return True
        self.client._rpc = rpc
        self.client.set_text_focused("việt")
        self.assertEqual(call_log, ["objInfo", "setText"])

    def test_paste_clipboard_text(self):
        call_log = []
        def rpc(method, *args, **kw):
            call_log.append((method, args))
            return True
        self.client._rpc = rpc
        self.client.paste_clipboard_text("café")
        self.assertEqual(
            call_log,
            [("setClipboard", ("device-farm", "café")), ("pasteClipboard", ())],
        )



if __name__ == "__main__":
    unittest.main()
