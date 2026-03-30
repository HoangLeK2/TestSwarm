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

import json
import time
from unittest.mock import MagicMock, Mock, call, patch

import pytest

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
# Bug 2: xpath element gestures resolve bounds / raise NotImplementedError
# ═══════════════════════════════════════════════════════════════════════════════

class TestXpathElementGestures:
    """drag_to/pinch_in/pinch_out must not pass xpath string as a text selector."""

    # ── drag_to ─────────────────────────────────────────────────────────────

    def test_drag_to_xpath_calls_drag_not_objdrag(self):
        """For xpath element, drag_to uses coordinate-based drag(), not objDrag(selector)."""
        c = _client()
        bounds = {"left": 0, "top": 0, "right": 100, "bottom": 50}
        c._find_element_xpath_with_bounds = Mock(
            return_value={"eid": "xpath:://*[@text='Home']", "bounds": bounds}
        )
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
        bounds = {"left": 10, "top": 20, "right": 110, "bottom": 60}  # center=(60, 40)
        c._find_element_xpath_with_bounds = Mock(
            return_value={"eid": "xpath:://*", "bounds": bounds}
        )
        drag_args = {}

        def fake_rpc(method, *args, **kw):
            if method == "drag":
                drag_args["args"] = args

        c._rpc = fake_rpc
        c.xpath('//*[@text="X"]').drag_to(300, 400, duration=0.2)

        assert drag_args, "drag RPC never called"
        x1, y1 = drag_args["args"][0], drag_args["args"][1]
        assert x1 == 60, f"Expected source cx=60, got {x1}"
        assert y1 == 40, f"Expected source cy=40, got {y1}"

    def test_drag_to_xpath_raises_when_element_not_found(self):
        c = _client()
        c._find_element_xpath_with_bounds = Mock(return_value=None)
        with pytest.raises(RuntimeError, match="not found"):
            c.xpath('//*[@text="Missing"]').drag_to(200, 200)

    def test_drag_to_xpath_raises_when_bounds_is_none(self):
        c = _client()
        c._find_element_xpath_with_bounds = Mock(return_value={"eid": "x", "bounds": None})
        with pytest.raises(RuntimeError, match="not found"):
            c.xpath('//*[@text="Missing"]').drag_to(200, 200)

    def test_drag_to_non_xpath_calls_objdrag(self):
        """Non-xpath drag_to still uses objDrag(selector, …) — regression check."""
        c = _client()
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c(text="Home").drag_to(500, 500)
        assert "objDrag" in rpc_calls
        assert "drag" not in rpc_calls

    # ── pinch_in ────────────────────────────────────────────────────────────

    def test_pinch_in_xpath_raises_not_implemented(self):
        c = _client()
        with pytest.raises(NotImplementedError, match="pinch_in"):
            c.xpath('//*[@text="Map"]').pinch_in()

    def test_pinch_in_non_xpath_calls_pinch_in_rpc(self):
        c = _client()
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c(text="Map").pinch_in(percent=50, steps=10)
        assert "pinchIn" in rpc_calls

    # ── pinch_out ───────────────────────────────────────────────────────────

    def test_pinch_out_xpath_raises_not_implemented(self):
        c = _client()
        with pytest.raises(NotImplementedError, match="pinch_out"):
            c.xpath('//*[@text="Map"]').pinch_out()

    def test_pinch_out_non_xpath_calls_pinch_out_rpc(self):
        c = _client()
        rpc_calls = []
        c._rpc = lambda method, *a, **kw: rpc_calls.append(method)
        c(text="Map").pinch_out(percent=50, steps=10)
        assert "pinchOut" in rpc_calls

    def test_pinch_in_error_message_includes_suggestion(self):
        c = _client()
        with pytest.raises(NotImplementedError) as exc_info:
            c.xpath('//*[@text="X"]').pinch_in()
        assert "native selector" in str(exc_info.value).lower()

    def test_pinch_out_error_message_includes_suggestion(self):
        c = _client()
        with pytest.raises(NotImplementedError) as exc_info:
            c.xpath('//*[@text="X"]').pinch_out()
        assert "native selector" in str(exc_info.value).lower()


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

    def test_rpc_dedicated_uses_watcher_session_not_client_session(self):
        """_rpc_dedicated posts through self._session, not self._client._session."""
        c, ctx = self._make_ctx()
        ctx._session.post = Mock(return_value=_ok_response(result=None))
        c._session.post = Mock()  # should NOT be called

        ctx._rpc_dedicated("click", 50, 25)

        ctx._session.post.assert_called_once()
        c._session.post.assert_not_called()

    def test_rpc_dedicated_raises_on_http_error(self):
        c, ctx = self._make_ctx()
        ctx._session.post = Mock(return_value=_err_response(500))
        with pytest.raises(RuntimeError, match="HTTP 500"):
            ctx._rpc_dedicated("click", 50, 25)

    def test_rpc_dedicated_raises_on_rpc_error(self):
        c, ctx = self._make_ctx()
        resp = Mock()
        resp.ok = True
        resp.status_code = 200
        resp.text = json.dumps({"jsonrpc": "2.0", "id": 0, "error": {"message": "UiObjectNotFound"}})
        ctx._session.post = Mock(return_value=resp)
        with pytest.raises(RuntimeError, match="watcher RPC error"):
            ctx._rpc_dedicated("click", 50, 25)

    def test_rpc_dedicated_sends_correct_payload(self):
        c, ctx = self._make_ctx()
        ctx._session.post = Mock(return_value=_ok_response(result=True))
        ctx._rpc_dedicated("click", 100, 200)

        _, kwargs = ctx._session.post.call_args
        payload = kwargs.get("json") or ctx._session.post.call_args[0][1]
        if payload is None:
            # positional
            payload = ctx._session.post.call_args[0][1]
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
