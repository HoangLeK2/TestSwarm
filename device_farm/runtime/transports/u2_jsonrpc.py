
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_RPC_PATH = "/jsonrpc/0"

# ── Selector mask constants (mirror openatx/android-uiautomator-server) ───────
_MASK_TEXT            = 0x01
_MASK_TEXT_CONTAINS   = 0x02
_MASK_TEXT_MATCHES    = 0x04
_MASK_TEXT_STARTSWITH = 0x08
_MASK_CLASS_NAME      = 0x10
_MASK_DESCRIPTION     = 0x40
_MASK_CHECKABLE       = 0x400
_MASK_CHECKED         = 0x800
_MASK_CLICKABLE       = 0x1000
_MASK_SCROLLABLE      = 0x4000
_MASK_ENABLED         = 0x8000
_MASK_FOCUSED         = 0x20000
_MASK_SELECTED        = 0x40000
_MASK_PACKAGE_NAME    = 0x80000
_MASK_RESOURCE_ID     = 0x200000
_MASK_INDEX           = 0x800000
_MASK_INSTANCE        = 0x1000000


class _U2JsonRpcElement:
    def __init__(self, client: "U2JsonRpcClient", by: str, value: str) -> None:
        self._client = client
        self._by = by
        self._value = value

    def click(self) -> None:
        eid = self._client.find_element(self._by, self._value)
        if eid is None:
            raise RuntimeError(f"Element not found: {self._by}={self._value!r}")
        self._client.element_click(eid)

    def wait(self, timeout: float = 10.0) -> bool:
        """Wait for element to appear using native waitForExists (server-side, no polling)."""
        return self._client._wait_for_exists(self._by, self._value, timeout)

    def wait_gone(self, timeout: float = 10.0) -> bool:
        """Wait for element to disappear using native waitUntilGone (server-side, no polling)."""
        return self._client._wait_until_gone(self._by, self._value, timeout)


class U2JsonRpcClient:
    """
    JSON-RPC 2.0 client for android-uiautomator-server running on port 9008.
    JsonRpc client for atx-agent / uiautomator2 HTTP API (same surface as classic u2 device).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9008,
                 timeout: float = 10.0) -> None:
        self._base = f"http://{host}:{port}"
        self._timeout = timeout
        # Touch operations (click/swipe) must not block for the full wait_timeout.
        # If the server is unresponsive, fail fast so the caller can reconnect.
        self._touch_timeout: float = min(timeout, 3.0)
        self._session = requests.Session()
        self._req_id = 0
        self.settings: Dict[str, Any] = {}
        self._implicitly_wait: float = 10.0

    # ── Connection ────────────────────────────────────────────────────────────

    def verify(self) -> Dict[str, Any]:
        """Check connectivity via a single JSON-RPC deviceInfo call (one TCP connection).
        Avoids the GET /ping + separate deviceInfo two-request pattern which causes
        two TCP reconnects on the device side (NanoHTTPD closes after each response)."""
        info = self._rpc("deviceInfo")  # single request — /ping would need a second RPC
        if not isinstance(info, dict) or "currentPackageName" not in info:
            raise RuntimeError(f"deviceInfo unexpected: {info!r}")
        logger.debug("U2JsonRpcClient connected: %s", info)
        return info

    def ping(self, timeout: Optional[float] = None) -> bool:
        """Keep-alive check via GET /ping — single lightweight request.
        Returns True if server responds with any valid HTTP 200."""
        try:
            t = timeout if timeout is not None else self._timeout
            r = self._session.get(self._base + "/ping", timeout=t)
            return r.status_code == 200
        except Exception:
            return False

    @property
    def device_info(self) -> Dict[str, Any]:
        return self._rpc("deviceInfo")

    def implicitly_wait(self, secs: float) -> None:
        self._implicitly_wait = secs

    # ── Gestures ──────────────────────────────────────────────────────────────

    def click(self, x: int, y: int) -> None:
        self._rpc("click", int(x), int(y), _timeout=self._touch_timeout)

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration: float = 0.5) -> None:
        steps = max(1, int(duration * 20))  # ~20 steps/sec
        # Add duration to timeout so long swipes don't time out prematurely.
        t = self._touch_timeout + duration
        self._rpc("swipe", int(x1), int(y1), int(x2), int(y2), steps, _timeout=t)

    def long_click(self, x: int, y: int, duration: float = 0.8) -> None:
        self._rpc("longClick", int(x), int(y), _timeout=self._touch_timeout + duration)

    # ── Element API ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_bounds(raw: Any) -> Optional[Dict[str, int]]:
        """Parse element bounds from either dict or Android string format '[x1,y1][x2,y2]'."""
        if isinstance(raw, dict):
            return raw  # already {"left": x, "top": y, "right": x2, "bottom": y2}
        if isinstance(raw, str) and raw.startswith("["):
            # Android format: "[left,top][right,bottom]"
            import re as _re
            nums = [int(n) for n in _re.findall(r"-?\d+", raw)]
            if len(nums) == 4:
                return {"left": nums[0], "top": nums[1], "right": nums[2], "bottom": nums[3]}
        return None

    def find_element(self, by: str, value: str,
                     timeout: Optional[float] = None) -> Optional[str]:
        """Find element using native waitForExists (server-side wait, timeout in ms).

        timeout=0  → instant check via objInfo (no wait, fastest)
        timeout>0  → server-side waitForExists (single blocking call)
        timeout=None → uses _implicitly_wait default (10s)

        Returns eid string or None. Raises on connection errors.
        """
        if by == "xpath":
            return self._find_element_xpath(value, timeout)
        wait_secs = timeout if timeout is not None else self._implicitly_wait

        selector = self._build_selector(by, value)

        # timeout=0: instant objInfo check (no server-side wait)
        if wait_secs <= 0:
            try:
                info = self._rpc("objInfo", selector)
                if info:
                    return f"{by}::{value}"
                return None
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "json-rpc error" in msg or "uiobjectnotfound" in msg:
                    return None
                raise
            except Exception:
                raise

        wait_ms = int(wait_secs * 1000)
        # HTTP timeout = wait time + buffer so request doesn't time out before server does
        rpc_timeout = wait_secs + 5.0
        try:
            found = self._rpc("waitForExists", selector, wait_ms, _timeout=rpc_timeout)
            if found:
                return f"{by}::{value}"
            return None
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "json-rpc error" in msg or "uiobjectnotfound" in msg:
                return None  # element not found — not a connection problem
            logger.debug("find_element %s=%r error: %s", by, value, exc)
            raise

    def _find_element_xpath(self, xpath_expr: str,
                            timeout: Optional[float] = None) -> Optional[str]:
        """Resolve xpath by dumping hierarchy XML and searching with ElementTree."""
        import xml.etree.ElementTree as ET
        wait = timeout if timeout is not None else self._implicitly_wait
        # Single check when timeout=0
        single_shot = wait <= 0
        deadline = time.monotonic() + max(wait, 0)
        while True:
            try:
                xml = self.page_source(timeout=self._timeout)
                if xml:
                    root = ET.fromstring(xml)
                    if root.findall(xpath_expr):
                        return f"xpath::{xpath_expr}"
            except Exception as exc:
                logger.debug("xpath find failed for %r: %s", xpath_expr, exc)
                raise
            if single_shot:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.5, remaining))
        return None

    def _wait_for_exists(self, by: str, value: str, timeout: float) -> bool:
        """Native waitForExists — server waits, returns bool. No Python polling."""
        if by == "xpath":
            return self._find_element_xpath(value, timeout) is not None
        selector = self._build_selector(by, value)
        wait_ms = int(timeout * 1000)
        try:
            result = self._rpc("waitForExists", selector, wait_ms,
                               _timeout=timeout + 5.0)
            return bool(result)
        except Exception:
            return False

    def _wait_until_gone(self, by: str, value: str, timeout: float) -> bool:
        """Native waitUntilGone — server waits, returns bool. No Python polling."""
        if by == "xpath":
            # No native xpath support in server — fall back to polling
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._find_element_xpath(value, 0) is None:
                    return True
                time.sleep(0.5)
            return False
        selector = self._build_selector(by, value)
        wait_ms = int(timeout * 1000)
        try:
            result = self._rpc("waitUntilGone", selector, wait_ms,
                               _timeout=timeout + 5.0)
            return bool(result)
        except Exception:
            return False

    def find_element_with_bounds(self, by: str, value: str) -> Optional[Dict[str, Any]]:
        """Find element and return {'eid': '...', 'bounds': {...}} or None. Single RPC call."""
        if by == "xpath":
            return self._find_element_xpath_with_bounds(value)
        selector = self._build_selector(by, value)
        try:
            info = self._rpc("objInfo", selector)
            if not info:
                return None
            raw_bounds = info.get("bounds") or info.get("visibleBounds")
            bounds = self._parse_bounds(raw_bounds)
            return {"eid": f"{by}::{value}", "bounds": bounds, "info": info}
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "json-rpc error" in msg or "uiobjectnotfound" in msg:
                return None
            raise

    def _find_element_xpath_with_bounds(self, xpath_expr: str) -> Optional[Dict[str, Any]]:
        """Resolve xpath via hierarchy XML, return eid + bounds."""
        import re as _re
        import xml.etree.ElementTree as ET
        try:
            xml = self.page_source(timeout=self._timeout)
            if not xml:
                return None
            root = ET.fromstring(xml)
            matches = root.findall(xpath_expr)
            if not matches:
                return None
            node = matches[0]
            bounds_str = node.get("bounds", "")
            nums = [int(n) for n in _re.findall(r"-?\d+", bounds_str)]
            bounds = {"left": nums[0], "top": nums[1], "right": nums[2], "bottom": nums[3]} if len(nums) == 4 else None
            return {"eid": f"xpath::{xpath_expr}", "bounds": bounds}
        except Exception as exc:
            logger.debug("xpath_with_bounds failed for %r: %s", xpath_expr, exc)
            raise

    def element_click(self, eid: str) -> None:
        """Click element by eid string (format: 'by::value').

        Resolves element bounds via find_element_with_bounds, then taps center.
        The JSON-RPC 'click(x, y)' only accepts coordinates, not a selector.
        """
        by, _, value = eid.partition("::")
        result = self.find_element_with_bounds(by, value)
        if result is None:
            raise RuntimeError(f"element_click: element not found {by}={value!r}")
        bounds = result.get("bounds")
        if not bounds:
            raise RuntimeError(f"element_click: no bounds for {by}={value!r}")
        cx = (bounds["left"] + bounds["right"]) // 2
        cy = (bounds["top"] + bounds["bottom"]) // 2
        self._rpc("click", cx, cy, _timeout=self._touch_timeout)

    def element_text(self, eid: str) -> str:
        by, _, value = eid.partition("::")
        selector = self._build_selector(by, value)
        try:
            result = self._rpc("getText", selector)
            return str(result or "")
        except Exception:
            return ""

    def page_source(self, timeout: Optional[float] = None) -> str:
        """
        Dump UI hierarchy XML via JSON-RPC dumpWindowHierarchy(False, 50).

        Retries up to 3 times with 1 s delay when hierarchy is empty or contains
        only '<hierarchy rotation="0" />' (accessibility service not ready yet).
        This mirrors the real uiautomator2 library behaviour.
        """
        t = timeout if timeout is not None else 60.0
        _empty_patterns = ('<hierarchy rotation="0" />', "<hierarchy />", "")
        for attempt in range(3):
            try:
                xml = str(self._rpc("dumpWindowHierarchy", False, 50, _timeout=t) or "")
                # Non-empty hierarchy that isn't a stub rotation placeholder
                if xml and not any(xml.strip() == p for p in _empty_patterns):
                    return xml
                logger.debug(
                    "dumpWindowHierarchy empty/stub (attempt %d/3): %r",
                    attempt + 1, xml[:80] if xml else ""
                )
            except RuntimeError as exc:
                msg = str(exc)
                if "JSON-RPC error" in msg or "empty response" in msg or "invalid response" in msg:
                    logger.debug(
                        "dumpWindowHierarchy server error (attempt %d/3): %s",
                        attempt + 1, exc
                    )
                else:
                    raise
            if attempt < 2:
                time.sleep(0.3)
        return ""

    # ── UiAutomator2-compatible API ───────────────────────────────────────────

    def app_start(self, package: str, activity: Optional[str] = None) -> None:
        params: Dict[str, Any] = {"pkg": package, "wait": True, "stop": False}
        if activity:
            params["cls"] = activity
        self._rpc("startActivity", **params)

    def app_stop(self, package: str) -> None:
        self._rpc("stopPackage", package)

    def app_current(self) -> Dict[str, str]:
        try:
            info = self._rpc("deviceInfo")
            pkg = info.get("currentPackageName", "")
            return {"package": pkg, "activity": ""}
        except Exception:
            return {"package": "", "activity": ""}

    def send_keys(self, text: str) -> None:
        self._rpc("setText", None, text)  # null selector = focused element

    def clear_text(self) -> None:
        self._rpc("clearTextField", None, 0, len(""))

    def xpath(self, xpath: str) -> _U2JsonRpcElement:
        return _U2JsonRpcElement(self, "xpath", xpath)

    def __call__(self, text: Optional[str] = None,
                 resourceId: Optional[str] = None, **kwargs: Any) -> _U2JsonRpcElement:
        if text is not None:
            return _U2JsonRpcElement(self, "text", text)
        if resourceId is not None:
            return _U2JsonRpcElement(self, "resource-id", resourceId)
        raise ValueError("Use d(text=...) or d(resourceId=...)")

    def wait_activity(self, activity: str, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cur = self.app_current()
            if activity in cur.get("activity", "") or activity in cur.get("package", ""):
                return True
            time.sleep(0.3)
        return False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _rpc(self, method: str, *args: Any, _timeout: Optional[float] = None,
             **kwargs: Any) -> Any:
        self._req_id += 1
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._req_id,
        }
        if args:
            payload["params"] = list(args)
        elif kwargs:
            payload["params"] = kwargs

        t = _timeout if _timeout is not None else self._timeout
        url = self._base + _RPC_PATH
        r = self._session.post(url, json=payload, timeout=t)
        r.raise_for_status()
        raw = r.text or ""
        if not raw.strip():
            raise RuntimeError("JSON-RPC empty response (tunnel reconnect?)")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"JSON-RPC invalid response: {raw[:200]!r}") from e
        if "error" in data:
            raise RuntimeError(f"JSON-RPC error: {data['error']}")
        return data.get("result")

    def _build_selector(self, by: str, value: str) -> Dict[str, Any]:
        """Convert W3C/WebDriver selector to uiautomator2 JSON-RPC selector with mask.

        The 'mask' bitmask MUST be included so the server knows which fields are
        active (openatx/android-uiautomator-server Selector protocol requirement).
        Without mask, objInfo / waitForExists match nothing.
        """
        if by in ("text",):
            return {"mask": _MASK_TEXT, "text": value}
        if by in ("textContains",):
            return {"mask": _MASK_TEXT_CONTAINS, "textContains": value}
        if by in ("textStartsWith",):
            return {"mask": _MASK_TEXT_STARTSWITH, "textStartsWith": value}
        if by in ("resource-id", "id"):
            return {"mask": _MASK_RESOURCE_ID, "resourceId": value}
        if by in ("class name", "className"):
            return {"mask": _MASK_CLASS_NAME, "className": value}
        if by in ("content-desc", "accessibility id", "description"):
            return {"mask": _MASK_DESCRIPTION, "description": value}
        if by in ("package",):
            return {"mask": _MASK_PACKAGE_NAME, "packageName": value}
        # Fallback: treat as text
        return {"mask": _MASK_TEXT, "text": value}
