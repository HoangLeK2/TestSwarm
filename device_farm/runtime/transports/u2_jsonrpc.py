from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from runtime.u2_xpath import (
    XPathElementNotFoundError,
    format_xpath_eid,
    node_bounds,
    node_center,
    normalize_u2_xpath,
    parse_xpath_eid,
)
from runtime.xml_utils import XML_PARSE_ERRORS, parse_xml

import requests

logger = logging.getLogger(__name__)

_RPC_PATH = "/jsonrpc/0"

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


# ── Relay HTTP session (duck-type requests.Session) ──────────────────────────

class _RelayResponse:
    """Duck-type replacement for requests.Response, built from a u2_result dict."""

    def __init__(self, result: dict) -> None:
        self.status_code: int = result.get("status", 0)
        self.ok: bool = result.get("ok", False) and 200 <= self.status_code < 300
        self._text: str = result.get("body", "")

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        return self._text.encode("utf-8") if isinstance(self._text, str) else self._text

    def json(self) -> Any:
        return json.loads(self._text)


class _RelaySession:
    """
    Drop-in replacement for requests.Session that routes HTTP calls through
    AdbRelayManager.u2_http() over the gRPC relay stream.

    NOTE (routing):
    - Any call that goes through this session is "u2 over agent-boot relay"
      (route label: agent_boot_u2_proxy).
    - This is still the legacy JSON-RPC wrapper path, not u2_batch/u2_flow.

    U2JsonRpcClient uses this transparently when the device is managed remotely.
    Assign to ``client._session`` after construction to activate relay mode.
    """

    def __init__(self, serial: str, relay_manager: Any, loop: Any) -> None:
        self._serial = serial
        self._relay = relay_manager
        self._loop = loop
        self.headers: Dict[str, str] = {"Accept-Encoding": ""}

    def _call(
        self,
        method: str,
        url: str,
        timeout: Any = 30.0,
        **kwargs: Any,
    ) -> "_RelayResponse":
        import asyncio
        from urllib.parse import urlparse

        if kwargs.get("files") is not None:
            raise NotImplementedError(
                "Multipart file upload (APK install) is not supported over the relay stream. "
                "Use URL-based install: client.install('https://...')"
            )

        t = float(timeout) if not isinstance(timeout, tuple) else float(timeout[1])
        body = ""
        content_type = "application/json"

        if kwargs.get("json") is not None:
            body = json.dumps(kwargs["json"])
        elif kwargs.get("data") is not None:
            raw = kwargs["data"]
            body = raw if isinstance(raw, str) else raw.decode("latin-1")

        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"

        future = asyncio.run_coroutine_threadsafe(
            self._relay.u2_http(self._serial, method.upper(), path, body, content_type, t),
            self._loop,
        )
        try:
            result = future.result(timeout=t + 15.0)
        except Exception as exc:
            result = {"ok": False, "status": 0, "body": str(exc), "content_type": ""}
        return _RelayResponse(result)

    def request(self, method: str, url: str, **kwargs: Any) -> _RelayResponse:
        """Generic request dispatcher (requests.Session-compatible)."""
        timeout = kwargs.pop("timeout", 30.0)
        return self._call(method.upper(), url, timeout, **kwargs)

    def get(self, url: str, timeout: Any = 30.0, **kwargs: Any) -> _RelayResponse:
        return self._call("GET", url, timeout, **kwargs)

    def post(self, url: str, timeout: Any = 30.0, **kwargs: Any) -> _RelayResponse:
        return self._call("POST", url, timeout, **kwargs)

    def put(self, url: str, timeout: Any = 30.0, **kwargs: Any) -> _RelayResponse:
        return self._call("PUT", url, timeout, **kwargs)

    def delete(self, url: str, timeout: Any = 30.0, **kwargs: Any) -> _RelayResponse:
        return self._call("DELETE", url, timeout, **kwargs)

    def close(self) -> None:
        pass  # no persistent connection to close


class _BatchRelaySession:
    """
    Sync adapter for u2_batch / u2_flow over the relay.
    Mirrors _RelaySession for the batch/flow surface only.

    NOTE (routing):
    - This is the dedicated "agent_boot_batch_flow" path.
    - Used by DeviceClient.tap_selector when batch is enabled.
    """

    def __init__(self, mgr: Any, serial: str, loop: Any) -> None:
        self._mgr = mgr
        self._serial = serial
        self._loop = loop

    def batch(self, actions: list[dict], timeout: float = 30.0) -> list[dict]:
        import asyncio
        fut = asyncio.run_coroutine_threadsafe(
            self._mgr.u2_batch(self._serial, actions, timeout=timeout),
            self._loop,
        )
        res = fut.result(timeout=timeout + 15.0)
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "u2_batch failed")
        return res.get("results") or []

    def flow(self, name: str, params: dict, timeout: float = 30.0) -> dict:
        import asyncio
        fut = asyncio.run_coroutine_threadsafe(
            self._mgr.u2_flow(self._serial, name, params, timeout=timeout),
            self._loop,
        )
        res = fut.result(timeout=timeout + 15.0)
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or f"u2_flow {name!r} failed")
        return res.get("value") or {}


# ── Watcher ───────────────────────────────────────────────────────────────────

class _WatcherEntry:
    """A single watcher rule: when condition matches → fire action."""

    def __init__(self, name: str, by: str, value: str) -> None:
        self.name = name
        self.by = by
        self.value = value
        self._action: Optional[tuple] = None  # ("click",) or ("press", key)

    def click(self) -> "_WatcherEntry":
        """Fire a click on the matched element when condition is met."""
        self._action = ("click",)
        return self

    def press(self, key: str) -> "_WatcherEntry":
        """Fire a key press when condition is met."""
        self._action = ("press", key)
        return self


class _WatcherBuilder:
    """Fluent builder returned by U2JsonRpcClient.watcher(name)."""

    def __init__(self, context: "_WatcherContext", name: str) -> None:
        self._context = context
        self._name = name

    def when(self,
             text: Optional[str] = None,
             textContains: Optional[str] = None,
             textStartsWith: Optional[str] = None,
             resourceId: Optional[str] = None,
             description: Optional[str] = None,
             className: Optional[str] = None) -> _WatcherEntry:
        if text is not None:
            by, value = "text", text
        elif textContains is not None:
            by, value = "textContains", textContains
        elif textStartsWith is not None:
            by, value = "textStartsWith", textStartsWith
        elif resourceId is not None:
            by, value = "resource-id", resourceId
        elif description is not None:
            by, value = "description", description
        elif className is not None:
            by, value = "className", className
        else:
            raise ValueError("when() requires at least one selector kwarg")
        entry = _WatcherEntry(self._name, by, value)
        self._context._entries[self._name] = entry
        return entry


class _WatcherContext:
    """
    Background watcher that polls the UI hierarchy and fires actions
    when registered conditions are met.

    Usage:
        client.watcher("dismiss_anr").when(text="Wait").click()
        client.watcher("dismiss_crash").when(textContains="stopped").press("back")
        client.watchers.start()          # begin polling every 2s
        ...
        client.watchers.stop()

    Thread safety: all HTTP uses the client's session under ``client._http_lock``
    so watcher polling never overlaps another RPC on the same TCP tunnel / relay
    stream (concurrent sessions caused mixed JSON bodies and duplicate tunnel reads).
    """

    def __init__(self, client: "U2JsonRpcClient") -> None:
        self._client = client
        self._entries: Dict[str, _WatcherEntry] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._interval = 2.0

    def __getitem__(self, name: str) -> _WatcherEntry:
        return self._entries[name]

    def __len__(self) -> int:
        return len(self._entries)

    def start(self, interval: float = 2.0) -> None:
        """Start the watcher background thread."""
        if self._running:
            return
        self._interval = interval
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="u2-watcher",
        )
        self._thread.start()
        logger.debug("Watcher started (interval=%.1fs, %d rules)", interval, len(self._entries))

    def stop(self) -> None:
        """Stop the watcher background thread."""
        self._running = False

    def remove(self, name: str) -> None:
        """Remove a registered watcher by name."""
        self._entries.pop(name, None)

    def reset(self) -> None:
        """Remove all registered watchers."""
        self._entries.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._run_once()
            except Exception as exc:
                logger.debug("watcher loop error: %s", exc)
            # Sleep in 0.5s ticks so stop() takes effect promptly.
            elapsed = 0.0
            while self._running and elapsed < self._interval:
                time.sleep(0.5)
                elapsed += 0.5

    def _run_once(self) -> None:
        if not self._entries:
            return
        xml_str = self._fetch_page_source()
        if not xml_str:
            return
        try:
            root = parse_xml(xml_str)
        except Exception:
            return
        for entry in list(self._entries.values()):
            if entry._action is None:
                continue
            try:
                self._check_and_fire(root, entry)
            except Exception as exc:
                logger.debug("watcher %r fire error: %s", entry.name, exc)

    def _check_and_fire(self, root: Any, entry: _WatcherEntry) -> None:
        node = self._find_node(root, entry)
        if node is None:
            return
        logger.debug("watcher %r matched: %s=%r", entry.name, entry.by, entry.value)
        action = entry._action
        if action[0] == "click":
            bounds = self._bounds_from_node(node)
            if bounds:
                cx = (bounds["left"] + bounds["right"]) // 2
                cy = (bounds["top"] + bounds["bottom"]) // 2
                # Use dedicated session to avoid racing with the main client session.
                self._rpc_dedicated("click", cx, cy)
        elif action[0] == "press":
            # press() probes multiple RPC method names; replicate the same strategy
            # through the dedicated session without touching main client state.
            k = (action[1] or "").strip().lower()
            for method in ("pressKey", "press", "key", "keyevent"):
                try:
                    self._rpc_dedicated(method, k)
                    return
                except Exception:
                    pass
            keycode = U2JsonRpcClient._KEYCODES.get(k)
            if keycode is not None:
                for method in ("pressKeyCode", "pressKeycode", "keyCode", "keycode"):
                    try:
                        self._rpc_dedicated(method, keycode)
                        return
                    except Exception:
                        pass
            logger.debug("watcher press(%r) unsupported via dedicated session", k)

    def _rpc_dedicated(self, method: str, *args: Any) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": method,
            "params": list(args),
        }
        with self._client._http_lock:
            r = self._client._session.post(
                self._client._base + _RPC_PATH,
                json=payload,
                timeout=self._client._touch_timeout,
            )
            if not r.ok:
                raise RuntimeError(f"watcher RPC HTTP {r.status_code}")
            data = json.loads(r.text or "{}")
            if "error" in data:
                raise RuntimeError(f"watcher RPC error: {data['error']}")
            return data.get("result")

    def _find_node(self, root: Any, entry: _WatcherEntry) -> Optional[Any]:
        """Find the first XML node matching entry's condition."""
        if entry.by == "xpath":
            query = U2JsonRpcClient._normalize_et_xpath(entry.value)
            try:
                matches = root.findall(query)
                return matches[0] if matches else None
            except Exception:
                return None
        for node in root.iter():
            if self._node_matches(node, entry.by, entry.value):
                return node
        return None

    @staticmethod
    def _node_matches(node: Any, by: str, value: str) -> bool:
        """Match an XML node against a by/value condition.

        Uses XML attribute names (resource-id, content-desc, class),
        NOT the JSON-RPC field names (resourceId, description, className).
        """
        if by == "text":
            return node.get("text", "") == value
        if by == "textContains":
            return value in node.get("text", "")
        if by == "textStartsWith":
            return node.get("text", "").startswith(value)
        if by in ("resource-id", "id"):
            return node.get("resource-id", "") == value
        if by in ("className", "class name"):
            return node.get("class", "") == value
        if by in ("description", "content-desc", "accessibility id"):
            return node.get("content-desc", "") == value
        if by == "package":
            return node.get("package", "") == value
        return False

    @staticmethod
    def _bounds_from_node(node: Any) -> Optional[Dict[str, int]]:
        bounds_str = node.get("bounds", "")
        nums = [int(n) for n in re.findall(r"-?\d+", bounds_str)]
        if len(nums) == 4:
            return {"left": nums[0], "top": nums[1], "right": nums[2], "bottom": nums[3]}
        return None

    def _fetch_page_source(self) -> str:
        """Fetch UI hierarchy via the client's session (under ``_http_lock``).

        Uses compressed=True so dumpWindowHierarchy skips off-screen/invisible
        sub-trees — same as the main hierarchy path.  The original False caused
        concurrent 3-10 s full dumps that overwhelmed u2's single-threaded
        NanoHTTPD and led to timeouts on the main session.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "dumpWindowHierarchy",
            "params": [True, 50],
        }
        try:
            with self._client._http_lock:
                r = self._client._session.post(
                    self._client._base + _RPC_PATH,
                    json=payload,
                    timeout=10.0,
                )
                if not r.ok:
                    return ""
                data = json.loads(r.text or "{}")
                return str(data.get("result") or "")
        except Exception:
            return ""


# ── Element proxy ─────────────────────────────────────────────────────────────

class _U2JsonRpcXMLElement:
    """Single node matched by an XPath query (u2 ``XMLElement`` subset)."""

    def __init__(
        self,
        client: "U2JsonRpcClient",
        node: Any,
        xpath_expr: str,
        index: int = 0,
    ) -> None:
        self._client = client
        self._node = node
        self._xpath_expr = xpath_expr
        self._index = index

    @property
    def text(self) -> str:
        return (self._node.get("text") or "").strip()

    @property
    def attrib(self) -> Dict[str, str]:
        return dict(self._node.attrib)

    @property
    def info(self) -> Dict[str, Any]:
        b = node_bounds(self._node)
        return {
            "text": self.text,
            "contentDescription": (self._node.get("content-desc") or "").strip(),
            "resourceId": (self._node.get("resource-id") or "").strip(),
            "className": (self._node.get("class") or "").strip(),
            "bounds": b,
            "clickable": (self._node.get("clickable") or "").lower() == "true",
        }

    def get_text(self) -> str:
        return self.text

    def center(self) -> Tuple[int, int]:
        b = node_bounds(self._node)
        if not b:
            raise RuntimeError(f"xpath element has no bounds: {self._xpath_expr!r}")
        return node_center(b)

    def click(self) -> None:
        cx, cy = self.center()
        self._client._rpc("click", cx, cy, _timeout=self._client._touch_timeout)

    def long_click(self, duration: float = 0.5) -> None:
        cx, cy = self.center()
        self._client._rpc(
            "click", cx, cy, int(duration * 1000),
            _timeout=self._client._touch_timeout + duration,
        )


class _U2JsonRpcElement:
    """
    Proxy for a UI element identified by a selector.

    Supports single-condition selectors (by/value) and multi-condition selectors
    (pre-built dict) created by U2JsonRpcClient.__call__(text="X", className="Y").

    When ``by == "xpath"``, implements uiautomator2 ``XPathSelector`` surface:
    click(timeout), click_exists, wait, wait_gone, get, get_text, set_text, all, …
    """

    def __init__(self, client: "U2JsonRpcClient", by: str, value: str,
                 selector: Optional[Dict[str, Any]] = None,
                 xpath_index: int = 0) -> None:
        self._client = client
        self._by = by
        if by == "xpath":
            self._value = normalize_u2_xpath(value)
        else:
            self._value = value
        self._selector: Optional[Dict[str, Any]] = selector
        self._xpath_index = max(0, int(xpath_index))

    def _is_xpath(self) -> bool:
        return self._by == "xpath"

    def _xpath_query(self) -> str:
        return U2JsonRpcClient._normalize_et_xpath(self._value)

    def _xpath_find_nodes(self, xml: Optional[str] = None) -> list:
        if xml is None:
            xml = self._client.page_source()
        if not xml:
            return []
        root = parse_xml(xml)
        return root.findall(self._xpath_query())

    def _xpath_get_node(self, xml: Optional[str] = None) -> Optional[Any]:
        nodes = self._xpath_find_nodes(xml)
        if self._xpath_index < len(nodes):
            return nodes[self._xpath_index]
        return None

    def _xpath_element(self, xml: Optional[str] = None) -> Optional[_U2JsonRpcXMLElement]:
        node = self._xpath_get_node(xml)
        if node is None:
            return None
        return _U2JsonRpcXMLElement(
            self._client, node, self._value, self._xpath_index,
        )

    def _native_proxy_for_xpath_node(self) -> Optional["_U2JsonRpcElement"]:
        """Use resource-id / text / description for pinch when the XML node has them."""
        node = self._xpath_get_node()
        if node is None:
            return None
        rid = (node.get("resource-id") or "").strip()
        if rid:
            return _U2JsonRpcElement(self._client, "resource-id", rid)
        txt = (node.get("text") or "").strip()
        if txt:
            return _U2JsonRpcElement(self._client, "text", txt)
        desc = (node.get("content-desc") or "").strip()
        if desc:
            return _U2JsonRpcElement(self._client, "description", desc)
        return None

    def _get_selector(self) -> Dict[str, Any]:
        if self._selector is not None:
            return self._selector
        return self._client._build_selector(self._by, self._value)

    # ── Introspection ──────────────────────────────────────────────────────────

    @property
    def exists(self) -> bool:
        if self._is_xpath():
            return self._xpath_get_node() is not None
        try:
            info = self._client._rpc("objInfo", self._get_selector())
            return bool(info)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "json-rpc error" in msg or "uiobjectnotfound" in msg:
                return False
            raise

    @property
    def count(self) -> int:
        if self._is_xpath():
            try:
                return len(self._xpath_find_nodes())
            except Exception:
                return 0
        try:
            result = self._client._rpc("count", self._get_selector())
            return int(result or 0)
        except Exception:
            return 0

    def all(self) -> list:
        """All xpath matches as ``_U2JsonRpcXMLElement`` (u2 ``XPathSelector.all()``)."""
        if not self._is_xpath():
            raise NotImplementedError("all() is only supported for xpath selectors")
        nodes = self._xpath_find_nodes()
        return [
            _U2JsonRpcXMLElement(self._client, n, self._value, i)
            for i, n in enumerate(nodes)
        ]

    def get_last_match(self) -> _U2JsonRpcXMLElement:
        if not self._is_xpath():
            raise NotImplementedError("get_last_match() is only for xpath")
        el = self._xpath_element()
        if el is None:
            raise XPathElementNotFoundError(self)
        return el

    def match(self) -> Optional[_U2JsonRpcXMLElement]:
        if not self._is_xpath():
            raise NotImplementedError("match() is only for xpath")
        return self._xpath_element()

    def __getitem__(self, index: int) -> "_U2JsonRpcElement":
        if self._is_xpath():
            return _U2JsonRpcElement(
                self._client, "xpath", self._value, xpath_index=int(index),
            )
        sel = dict(self._get_selector())
        sel["instance"] = index
        sel["mask"] = sel.get("mask", 0) | _MASK_INSTANCE
        return _U2JsonRpcElement(self._client, self._by, self._value, selector=sel)

    # ── Actions ───────────────────────────────────────────────────────────────

    def click(self, timeout: Optional[float] = None) -> None:
        if self._is_xpath():
            el = self.get(timeout=timeout)
            el.click()
            return
        if self._selector is not None:
            result = self._client._find_with_selector(self._selector)
            if result is None:
                raise RuntimeError(f"Element not found: {self._selector!r}")
            bounds = result.get("bounds")
            if not bounds:
                raise RuntimeError(f"Element bounds unavailable: {self._selector!r}")
            cx = (bounds["left"] + bounds["right"]) // 2
            cy = (bounds["top"] + bounds["bottom"]) // 2
            self._client._rpc("click", cx, cy, _timeout=self._client._touch_timeout)
            return
        eid = self._client.find_element(self._by, self._value)
        if eid is None:
            raise RuntimeError(f"Element not found: {self._by}={self._value!r}")
        self._client.element_click(eid)

    def click_nowait(self) -> None:
        if not self._is_xpath():
            raise NotImplementedError("click_nowait() is only for xpath")
        el = self._xpath_element()
        if el is None:
            raise XPathElementNotFoundError(self)
        el.click()

    def click_exists(self, timeout: Optional[float] = None) -> bool:
        if not self._is_xpath():
            if timeout:
                if not self.wait(timeout=timeout):
                    return False
            try:
                self.click()
                return True
            except RuntimeError:
                return False
        try:
            self.get(timeout=timeout).click()
            return True
        except XPathElementNotFoundError:
            return False

    def get(self, timeout: Optional[float] = None) -> _U2JsonRpcXMLElement:
        if not self._is_xpath():
            raise NotImplementedError("get() is only for xpath selectors")
        wait_secs = (
            timeout if timeout is not None else self._client._implicitly_wait
        )
        if not self.wait(timeout=wait_secs):
            raise XPathElementNotFoundError(self)
        el = self._xpath_element()
        if el is None:
            raise XPathElementNotFoundError(self)
        return el

    def get_text(self) -> str:
        if self._is_xpath():
            return self.get().get_text()
        eid = self._client.find_element(self._by, self._value, timeout=0)
        if eid is None:
            raise XPathElementNotFoundError(self)
        return self._client.element_text(eid)

    def set_text(self, text: str) -> None:
        if self._is_xpath():
            el = self.get()
            el.click()
            time.sleep(0.15)
            self._client.clear_text()
            time.sleep(0.15)
            self._client.send_keys(text)
            return
        eid = self._client.find_element(self._by, self._value)
        if eid is None:
            raise XPathElementNotFoundError(self)
        self._client.element_click(eid)
        time.sleep(0.15)
        self._client.clear_text()
        time.sleep(0.15)
        self._client.send_keys(text)

    def wait(self, timeout: Optional[float] = None) -> bool:
        if self._is_xpath():
            wait_secs = (
                timeout if timeout is not None else self._client._implicitly_wait
            )
            deadline = time.monotonic() + max(wait_secs, 0)
            while True:
                if self.exists:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.2)
        if self._selector is not None:
            return self._client._wait_with_selector(
                self._selector, "waitForExists", timeout or 10.0,
            )
        return self._client._wait_for_exists(
            self._by, self._value, timeout if timeout is not None else 10.0,
        )

    def wait_gone(self, timeout: Optional[float] = None) -> bool:
        if self._is_xpath():
            wait_secs = (
                timeout if timeout is not None else self._client._implicitly_wait
            )
            deadline = time.monotonic() + max(wait_secs, 0)
            while time.monotonic() < deadline:
                if not self.exists:
                    return True
                time.sleep(0.2)
            return False
        if self._selector is not None:
            return self._client._wait_with_selector(
                self._selector, "waitUntilGone", timeout or 10.0,
            )
        return self._client._wait_until_gone(
            self._by, self._value, timeout if timeout is not None else 10.0,
        )

    def drag_to(self, x: int, y: int, duration: float = 0.5) -> None:
        steps = max(1, int(duration * 20))
        t = self._client._touch_timeout + duration
        if self._is_xpath():
            el = self.get(timeout=0)
            cx, cy = el.center()
            self._client._rpc("drag", cx, cy, int(x), int(y), steps, _timeout=t)
            return
        self._client._rpc(
            "objDrag", self._get_selector(), int(x), int(y), steps, _timeout=t,
        )

    def pinch_in(self, percent: int = 50, steps: int = 10) -> None:
        if self._is_xpath():
            proxy = self._native_proxy_for_xpath_node()
            if proxy is None:
                raise RuntimeError(
                    "pinch_in: xpath node has no text/resource-id/description "
                    "for native pinch — use coordinates or a native selector"
                )
            proxy.pinch_in(percent=percent, steps=steps)
            return
        self._client._rpc(
            "pinchIn", self._get_selector(), percent, steps,
            _timeout=self._client._touch_timeout + steps * 0.05,
        )

    def pinch_out(self, percent: int = 50, steps: int = 10) -> None:
        if self._is_xpath():
            proxy = self._native_proxy_for_xpath_node()
            if proxy is None:
                raise RuntimeError(
                    "pinch_out: xpath node has no text/resource-id/description "
                    "for native pinch — use coordinates or a native selector"
                )
            proxy.pinch_out(percent=percent, steps=steps)
            return
        self._client._rpc(
            "pinchOut", self._get_selector(), percent, steps,
            _timeout=self._client._touch_timeout + steps * 0.05,
        )


# ── Client ────────────────────────────────────────────────────────────────────

class U2JsonRpcClient:
    """
    JSON-RPC 2.0 client for android-uiautomator-server running on port 9008.
    Talks directly to uiautomator-server — no atx-agent required.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9008,
                 timeout: float = 10.0,
                 adb_shell: Optional[Callable[[str], str]] = None) -> None:
        self._base = f"http://{host}:{port}"
        self._timeout = timeout
        # Touch operations (click/swipe) must not block for the full wait_timeout.
        # If the server is unresponsive, fail fast so the caller can reconnect.
        self._touch_timeout: float = min(timeout, 3.0)
        self._session = requests.Session()
        # Disable gzip: NanoHTTPD has a known resource leak with gzip encoding.
        # https://github.com/NanoHttpd/nanohttpd/issues/492
        self._session.headers.update({"Accept-Encoding": ""})
        # Serialize every HTTP transaction: Session is not thread-safe, and a
        # second TCP to the local tunnel (e.g. from a parallel Session) breaks u2.
        self._http_lock = threading.RLock()
        self._req_id = 0
        self.settings: Dict[str, Any] = {}
        self._implicitly_wait: float = 10.0
        # Cache working press method after first success to avoid 8 RPC retries
        self._press_method: Optional[str] = None
        self._press_keycode_method: Optional[str] = None
        # Optional ADB shell callable (transport.shell_safe) for operations
        # that require ADB (e.g. app_start via `am start`).
        self._adb_shell: Optional[Callable[[str], str]] = adb_shell
        # Watcher context (background popup dismissal)
        self.watchers = _WatcherContext(self)

    # ── Connection ────────────────────────────────────────────────────────────

    def verify(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Check connectivity via a single JSON-RPC deviceInfo call (one TCP connection).
        Avoids the GET /ping + separate deviceInfo two-request pattern which causes
        two TCP reconnects on the device side (NanoHTTPD closes after each response).

        timeout: override the HTTP read timeout for this call only.  Pass a short
        value (e.g. 8.0) when probing during reconnect so a dead server fails fast
        instead of blocking for the full wait_timeout (default 20 s).
        """
        kw: Dict[str, Any] = {"_timeout": timeout} if timeout is not None else {}
        info = self._rpc("deviceInfo", **kw)
        if not isinstance(info, dict) or "currentPackageName" not in info:
            raise RuntimeError(f"deviceInfo unexpected: {info!r}")
        logger.debug("U2JsonRpcClient connected: %s", info)
        return info

    def ping(self, timeout: Optional[float] = None) -> bool:
        """Keep-alive check via GET /ping — single lightweight request.
        Returns True if server responds with any valid HTTP 200."""
        try:
            t = timeout if timeout is not None else self._timeout
            with self._http_lock:
                r = self._session.get(self._base + "/ping", timeout=t)
            return r.status_code == 200
        except Exception:
            return False

    def screenshot(self, timeout: float = 10.0, max_width: int = 800, quality: int = 70) -> Optional[bytes]:
        """
        Capture screenshot via u2 HTTP API (GET /screenshot/0).
        Returns JPEG bytes, resized to max_width if needed.
        Returns None on failure.

        NOTE (routing):
        - If self._session is requests.Session: local u2 wrapper path.
        - If self._session is _RelaySession: u2 wrapper via agent-boot relay.
        """
        try:
            with self._http_lock:
                r = self._session.get(self._base + "/screenshot/0", timeout=timeout)
            if r.status_code != 200:
                logger.warning("U2 screenshot failed: HTTP %d", r.status_code)
                return None
            img_bytes = r.content
            if not img_bytes:
                return None
            # Resize + re-encode to JPEG if needed
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(img_bytes))
                w, h = img.size
                if max_width > 0 and w > max_width:
                    ratio = max_width / w
                    new_h = int(h * ratio)
                    img = img.resize((max_width, new_h), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                return buf.getvalue()
            except ImportError:
                # PIL not available — return raw bytes as-is
                return img_bytes
        except Exception as exc:
            logger.debug("U2 screenshot error: %s", exc)
            return None

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
        steps = max(1, int(duration * 40))  # ~40 steps/sec — higher step rate = lower velocity at lift = no fling
        # Add duration to timeout so long swipes don't time out prematurely.
        t = self._touch_timeout + duration
        self._rpc("swipe", int(x1), int(y1), int(x2), int(y2), steps, _timeout=t)

    def drag(self, x1: int, y1: int, x2: int, y2: int,
             duration: float = 0.5) -> None:
        """Drag from (x1, y1) to (x2, y2) by screen coordinates."""
        steps = max(1, int(duration * 20))
        t = self._touch_timeout + duration
        self._rpc("drag", int(x1), int(y1), int(x2), int(y2), steps, _timeout=t)

    def long_click(self, x: int, y: int, duration: float = 0.8) -> None:
        self._rpc("longClick", int(x), int(y), _timeout=self._touch_timeout + duration)

    def double_click(self, x: int, y: int) -> None:
        """Double-tap at screen coordinates. Falls back to two rapid clicks if server lacks doubleClick."""
        import time as _time
        try:
            self._rpc("doubleClick", int(x), int(y), _timeout=self._touch_timeout)
        except Exception:
            self._rpc("click", int(x), int(y), _timeout=self._touch_timeout)
            _time.sleep(0.1)
            self._rpc("click", int(x), int(y), _timeout=self._touch_timeout)

    # ── Key events ────────────────────────────────────────────────────────────

    _KEYCODES: Dict[str, int] = {
        "home": 3, "back": 4, "menu": 82, "power": 26,
        "enter": 66, "del": 67, "delete": 67, "tab": 61,
        "recent": 187, "app_switch": 187,
        "volumeup": 24, "volumedown": 25,
    }

    def press_ime(self) -> None:
        """Press the IME action button (Search/Go/Done/Next) on the active text field.

        More reliable than KEYCODE_ENTER for search/form submission — triggers the
        imeOptions action (actionSearch, actionGo, actionDone) rather than a raw newline.
        Falls back to KEYCODE_ENTER if pressImeActionButton is not available.
        """
        for method in ("pressImeActionButton", "pressImeAction"):
            try:
                self._rpc(method)
                return
            except Exception:
                pass
        self.press("enter")

    def press(self, key: str) -> None:
        """
        Press a device key via uiautomator2 instrumentation (e.g. "home", "back").

        Caches the working RPC method name after the first successful call so
        subsequent presses cost exactly 1 RPC instead of up to 8 retries.
        """
        k = (key or "").strip().lower()
        if not k:
            return

        last_exc: Exception | None = None

        # Fast path: use cached string method
        if self._press_method:
            try:
                self._rpc(self._press_method, k)
                return
            except Exception as exc:
                last_exc = exc
                self._press_method = None  # cache miss — re-probe below

        # Probe string-based APIs once, cache winner
        for method in ("pressKey", "press", "key", "keyevent"):
            try:
                self._rpc(method, k)
                self._press_method = method
                return
            except Exception as exc:
                last_exc = exc

        # Keycode fallback
        keycode = self._KEYCODES.get(k)
        if keycode is None:
            raise RuntimeError(f"u2 press({k!r}) unsupported: {last_exc}")

        # Fast path: use cached keycode method
        if self._press_keycode_method:
            try:
                self._rpc(self._press_keycode_method, keycode)
                return
            except Exception as exc:
                last_exc = exc
                self._press_keycode_method = None

        for method in ("pressKeyCode", "pressKeycode", "keyCode", "keycode"):
            try:
                self._rpc(method, keycode)
                self._press_keycode_method = method
                return
            except Exception as exc:
                last_exc = exc

        raise RuntimeError(f"u2 press({k!r}) unsupported: {last_exc}")

    # ── Element API ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_bounds(raw: Any) -> Optional[Dict[str, int]]:
        """Parse element bounds from either dict or Android string format '[x1,y1][x2,y2]'."""
        if isinstance(raw, dict):
            return raw  # already {"left": x, "top": y, "right": x2, "bottom": y2}
        if isinstance(raw, str) and raw.startswith("["):
            # Android format: "[left,top][right,bottom]"
            nums = [int(n) for n in re.findall(r"-?\d+", raw)]
            if len(nums) == 4:
                return {"left": nums[0], "top": nums[1], "right": nums[2], "bottom": nums[3]}
        return None

    def find_element_spec(self, spec: Any,
                          timeout: Optional[float] = None) -> Optional[str]:
        """Find element from ScenarioSelectorSpec (multi-field AND, xpath, chain→xpath)."""
        from services.scenario_selector import (
            ScenarioSelectorSpec,
            _parse_selector_dict,
            compile_chain_to_xpath,
            spec_has_chain,
            spec_to_rpc_selector,
            spec_eid,
        )
        if isinstance(spec, dict):
            spec = _parse_selector_dict(spec)
        if not isinstance(spec, ScenarioSelectorSpec) or spec.is_empty():
            return None
        if spec_has_chain(spec):
            xpath = compile_chain_to_xpath(spec)
            if xpath:
                eid = self._find_element_xpath(xpath, timeout)
                return eid
            return None
        rpc = spec_to_rpc_selector(spec)
        if "_xpath" in rpc:
            return self._find_element_xpath(rpc["_xpath"], timeout)
        wait_secs = timeout if timeout is not None else self._implicitly_wait
        if wait_secs <= 0:
            try:
                info = self._rpc("objInfo", rpc)
                if info:
                    return spec_eid(spec)
                return None
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "json-rpc error" in msg or "uiobjectnotfound" in msg:
                    return None
                raise
        wait_ms = int(wait_secs * 1000)
        rpc_timeout = wait_secs + 5.0
        try:
            found = self._rpc("waitForExists", rpc, wait_ms, _timeout=rpc_timeout)
            if found:
                return spec_eid(spec)
            return None
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "json-rpc error" in msg or "uiobjectnotfound" in msg:
                return None
            raise

    def find_element_with_bounds_spec(self, spec: Any,
                                      timeout: Optional[float] = None
                                      ) -> Optional[Dict[str, Any]]:
        """Find element spec and return eid + bounds."""
        from services.scenario_selector import (
            ScenarioSelectorSpec,
            _parse_selector_dict,
            compile_chain_to_xpath,
            spec_has_chain,
            spec_to_rpc_selector,
            spec_eid,
        )
        if isinstance(spec, dict):
            spec = _parse_selector_dict(spec)
        if not isinstance(spec, ScenarioSelectorSpec) or spec.is_empty():
            return None
        if spec_has_chain(spec):
            xpath = compile_chain_to_xpath(spec)
            if xpath:
                return self._find_element_xpath_with_bounds(xpath)
            return None
        rpc = spec_to_rpc_selector(spec)
        if "_xpath" in rpc:
            return self._find_element_xpath_with_bounds(rpc["_xpath"])
        eid = self.find_element_spec(spec, timeout=timeout or 0)
        if not eid:
            return None
        try:
            info = self._rpc("objInfo", rpc)
            if not info:
                return None
            raw_bounds = info.get("bounds") or info.get("visibleBounds")
            bounds = self._parse_bounds(raw_bounds)
            return {"eid": eid, "bounds": bounds, "info": info}
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "json-rpc error" in msg or "uiobjectnotfound" in msg:
                return None
            raise

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
                            timeout: Optional[float] = None,
                            index: int = 0) -> Optional[str]:
        """Resolve xpath by dumping hierarchy XML and searching with ElementTree."""
        expr = normalize_u2_xpath(xpath_expr)
        xpath_query = self._normalize_et_xpath(expr)
        wait = timeout if timeout is not None else self._implicitly_wait
        single_shot = wait <= 0
        deadline = time.monotonic() + max(wait, 0)
        while True:
            try:
                remaining = deadline - time.monotonic()
                ps_timeout = min(self._timeout, max(0.5, remaining + 1.0))
                xml = self.page_source(timeout=ps_timeout)
                if xml:
                    root = parse_xml(xml)
                    matches = root.findall(xpath_query)
                    if len(matches) > index:
                        return format_xpath_eid(expr, index)
            except Exception as exc:
                logger.debug("xpath find failed for %r: %s", xpath_expr, exc)
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

    def find_element_with_bounds(self, by: str, value: str,
                                 index: int = 0) -> Optional[Dict[str, Any]]:
        """Find element and return {'eid': '...', 'bounds': {...}} or None. Single RPC call."""
        if by == "xpath":
            return self._find_element_xpath_with_bounds(value, index=index)
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

    def _find_element_xpath_with_bounds(self, xpath_expr: str,
                                        index: int = 0) -> Optional[Dict[str, Any]]:
        """Resolve xpath via hierarchy XML, return eid + bounds."""
        expr = normalize_u2_xpath(xpath_expr)
        xpath_query = self._normalize_et_xpath(expr)
        try:
            xml = self.page_source(timeout=self._timeout)
            if not xml:
                return None
            root = parse_xml(xml)
            matches = root.findall(xpath_query)
            if index >= len(matches):
                return None
            node = matches[index]
            bounds = node_bounds(node)
            return {"eid": format_xpath_eid(expr, index), "bounds": bounds}
        except Exception as exc:
            logger.debug("xpath_with_bounds failed for %r: %s", xpath_expr, exc)
            raise

    @staticmethod
    def _normalize_et_xpath(xpath_expr: str) -> str:
        """
        ElementTree's Element.findall() rejects absolute paths like '//*' with:
        'cannot use absolute path on element'. Convert common absolute forms
        to relative descendants rooted at current element.
        """
        q = (xpath_expr or "").strip()
        if q.startswith("//"):
            return f".{q}"  # //... -> .//...
        if q.startswith("/"):
            return f".{q}"  # /a/b -> ./a/b
        return q

    def element_click(self, eid: str) -> None:
        """Click element by eid string (format: 'by::value' or 'xpath::{index}::{expr}').

        Resolves element bounds via find_element_with_bounds, then taps center.
        The JSON-RPC 'click(x, y)' only accepts coordinates, not a selector.
        """
        if eid.startswith("xpath::"):
            expr, index = parse_xpath_eid(eid)
            result = self.find_element_with_bounds("xpath", expr, index=index)
            label = eid
        else:
            by, _, value = eid.partition("::")
            result = self.find_element_with_bounds(by, value)
            label = f"{by}={value!r}"
        if result is None:
            raise RuntimeError(f"element_click: element not found {label}")
        bounds = result.get("bounds")
        if not bounds:
            raise RuntimeError(f"element_click: no bounds for {label}")
        cx = (bounds["left"] + bounds["right"]) // 2
        cy = (bounds["top"] + bounds["bottom"]) // 2
        self._rpc("click", cx, cy, _timeout=self._touch_timeout)

    def element_text(self, eid: str) -> str:
        if eid.startswith("xpath::"):
            expr, index = parse_xpath_eid(eid)
            result = self._find_element_xpath_with_bounds(expr, index=index)
            if not result:
                return ""
            xml = self.page_source(timeout=self._timeout)
            if not xml:
                return ""
            root = parse_xml(xml)
            q = self._normalize_et_xpath(normalize_u2_xpath(expr))
            matches = root.findall(q)
            if index < len(matches):
                return (matches[index].get("text") or "").strip()
            return ""
        by, _, value = eid.partition("::")
        selector = self._build_selector(by, value)
        try:
            result = self._rpc("getText", selector)
            return str(result or "")
        except Exception:
            return ""

    def page_source(self, timeout: Optional[float] = None,
                    compressed: bool = False) -> str:
        """
        Dump UI hierarchy XML via JSON-RPC dumpWindowHierarchy(compressed, 50).

        compressed=True  → server skips redundant layout nodes (faster, smaller XML).
        compressed=False → full hierarchy (default, compatible with all devices).

        Retries up to 3 times with 300ms delay when hierarchy is empty or the
        root has no children (accessibility service not ready yet).
        This mirrors the real uiautomator2 library behaviour.
        """
        t = timeout if timeout is not None else 60.0
        for attempt in range(3):
            try:
                xml = str(self._rpc("dumpWindowHierarchy", compressed, 50, _timeout=t) or "")
                if xml:
                    try:
                        root = parse_xml(xml)
                        if list(root):  # has at least one child node
                            return xml
                    except Exception:
                        pass  # invalid XML — treat as empty, retry
                logger.debug(
                    "dumpWindowHierarchy empty/stub (attempt %d/3): %r",
                    attempt + 1, xml[:80] if xml else ""
                )
            except RuntimeError as exc:
                msg = str(exc)
                # Retry on transient server errors (empty body, bad JSON, HTTP 5xx).
                # "JSON-RPC HTTP" covers the r.ok-based error from _rpc().
                if any(pat in msg for pat in (
                    "JSON-RPC error", "JSON-RPC HTTP",
                    "empty response", "invalid response",
                )):
                    logger.debug(
                        "dumpWindowHierarchy server error (attempt %d/3): %s",
                        attempt + 1, exc
                    )
                else:
                    raise
            if attempt < 2:
                time.sleep(0.3)
        return ""

    # ── App / Session API ─────────────────────────────────────────────────────

    def app_start(
        self,
        package: str,
        activity: Optional[str] = None,
        *,
        stop: bool = False,
        use_monkey: bool = False,
    ) -> None:
        """Launch an app via `adb shell am start` or monkey.

        android-uiautomator-server has no `startActivity` RPC — app launch must
        go through ADB. If no adb_shell callable was provided at construction,
        raises RuntimeError with a clear message instead of silently sending a
        broken JSON-RPC call.
        """
        if self._adb_shell is None:
            raise RuntimeError(
                "app_start() requires an adb_shell callable. "
                "Pass adb_shell=transport.shell_safe when constructing U2JsonRpcClient."
            )
        if stop:
            try:
                self.app_stop(package)
            except Exception:
                self._adb_shell(f"am force-stop {package}")
        if use_monkey:
            self._adb_shell(
                f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
            )
            return
        if activity:
            act = activity if activity.startswith(".") else activity
            if "/" not in act:
                component = f"{package}/{act}"
            else:
                component = act
            cmd = f"am start -n {component} -W"
        else:
            cmd = (
                f"am start -W"
                f" -a android.intent.action.MAIN"
                f" -c android.intent.category.LAUNCHER"
                f" -p {package}"
            )
        self._adb_shell(cmd)

    def app_stop(self, package: str) -> None:
        try:
            self._rpc("stopPackage", package)
        except Exception:
            if self._adb_shell is not None:
                self._adb_shell(f"am force-stop {package}")
            else:
                raise

    def app_clear(self, package: str) -> None:
        """Clear app data (`pm clear`). Requires adb_shell."""
        if self._adb_shell is None:
            raise RuntimeError(
                "app_clear() requires an adb_shell callable. "
                "Pass adb_shell=transport.shell_safe when constructing U2JsonRpcClient."
            )
        self._adb_shell(f"pm clear {package}")

    def app_wait(self, package: str, front: bool = False,
                 timeout: float = 20.0) -> bool:
        """Wait until `package` is the foreground app.

        Polls deviceInfo.currentPackageName every 0.5 s until timeout.
        deviceInfo only exposes the foreground package, so both front=True and
        front=False reduce to the same check.

        Returns True if the condition is met within timeout, False otherwise.
        """
        del front  # accepted for compat; deviceInfo has no background-process check
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                info = self._rpc("deviceInfo")
                if (info or {}).get("currentPackageName", "") == package:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    @contextlib.contextmanager
    def session(self, package: str, activity: Optional[str] = None,
                launch_timeout: float = 20.0) -> Iterator["U2JsonRpcClient"]:
        """
        Context manager that launches an app fresh and stops it on exit.

        Stops any running instance → launches → waits for foreground → yields self.
        On exit (normal or exception) stops the app.

        Usage:
            with client.session("com.example.app") as s:
                s.click(100, 200)
                s.xpath('//android.widget.Button').click()
                s(text="Login").click()
        """
        self.app_stop(package)
        self.app_start(package, activity)
        if not self.app_wait(package, timeout=launch_timeout):
            raise RuntimeError(
                f"session: {package!r} did not reach foreground within {launch_timeout}s"
            )
        try:
            yield self
        finally:
            try:
                self.app_stop(package)
            except Exception:
                pass

    def app_current(self) -> Dict[str, str]:
        try:
            info = self._rpc("deviceInfo")
            pkg = info.get("currentPackageName", "")
            return {"package": pkg, "activity": ""}
        except Exception:
            return {"package": "", "activity": ""}

    def send_keys(self, text: str) -> None:
        """
        Type text into the currently focused input field.

        Strategy (same as official uiautomator2):
        1. Find focused element via objInfo with isFocused=true selector.
        2. Call setText on that element.
        3. Fall back to setFastInputText (IME injection) if setText fails —
           works even when no element reports focus (e.g. WebView inputs).
        """
        focused_selector = {"mask": _MASK_FOCUSED, "focused": True}
        try:
            info = self._rpc("objInfo", focused_selector)
            if info:
                self._rpc("setText", focused_selector, text)
                return
        except Exception:
            pass
        # Fallback: IME-based injection (setFastInputText / sendKeys).
        # These take a single text argument and do not require a selector,
        # so they survive scenarios where no element reports focus (e.g.
        # WebView inputs, pre-focus races right after element_click).
        for method in ("setFastInputText", "sendKeys"):
            try:
                self._rpc(method, text)
                return
            except Exception:
                pass
        # Intentionally no `setText(null, text)` last-resort — it raises
        # JSON-RPC -32602 "method parameters invalid" on every device we've
        # seen and masks the real "no focused input" condition from the
        # caller. Surface a RuntimeError instead so the scenario step reports
        # actionable context rather than a cryptic JSON-RPC code.
        raise RuntimeError("send_keys: no focused input field and IME injection failed")

    def clear_text(self) -> None:
        """Clear the currently focused text field. No-op if nothing focused.

        The old `clearTextField(null, 0, 9999)` fallback was what triggered
        the u2 "JSON-RPC error -32602 method parameters invalid" on devices
        where the post-click focus had not landed yet — `null` is not a
        valid UiSelector for that JSON-RPC method. We now skip the fallback
        entirely and let the caller proceed to `send_keys`, which has its
        own selector-less IME-injection path that does work (setFastInputText).
        """
        focused_selector = {"mask": _MASK_FOCUSED, "focused": True}
        try:
            info = self._rpc("objInfo", focused_selector)
            if info:
                self._rpc("clearTextField", focused_selector, 0, 9999)
        except Exception:
            # Nothing focused / no editable in focus — caller will retry
            # the text entry via the IME fallback in send_keys().
            pass

    def set_clipboard(self, text: str) -> bool:
        """Set device clipboard text via uiautomator2 server. Returns True on success."""
        for method in ("setClipboard", "clipboardSet", "clipboard"):
            try:
                self._rpc(method, text)
                return True
            except Exception:
                pass
        return False

    def get_clipboard(self) -> Optional[str]:
        """Get device clipboard text via uiautomator2 server."""
        for method in ("getClipboard", "clipboardGet", "clipboard"):
            try:
                result = self._rpc(method)
                if isinstance(result, str):
                    return result
            except Exception:
                pass
        return None

    # ── Element builder ───────────────────────────────────────────────────────

    def xpath(self, xpath_expr: str) -> _U2JsonRpcElement:
        """uiautomator2-compatible XPath selector (supports ``@resource-id`` sugar)."""
        return _U2JsonRpcElement(self, "xpath", xpath_expr)

    def watcher(self, name: str) -> _WatcherBuilder:
        """Register a named watcher rule.

        Usage:
            client.watcher("dismiss_anr").when(text="Wait").click()
            client.watcher("dismiss_crash").when(textContains="stopped").press("back")
            client.watchers.start()
        """
        return _WatcherBuilder(self.watchers, name)

    def __call__(self, text: Optional[str] = None,
                 resourceId: Optional[str] = None,
                 description: Optional[str] = None,
                 className: Optional[str] = None,
                 textContains: Optional[str] = None,
                 textStartsWith: Optional[str] = None,
                 package: Optional[str] = None,
                 **kwargs: Any) -> _U2JsonRpcElement:
        # Collect all provided conditions with canonical by-names
        conditions: Dict[str, str] = {}
        if text is not None:             conditions["text"]          = text
        if resourceId is not None:       conditions["resource-id"]   = resourceId
        if description is not None:      conditions["description"]   = description
        if className is not None:        conditions["className"]     = className
        if textContains is not None:     conditions["textContains"]  = textContains
        if textStartsWith is not None:   conditions["textStartsWith"] = textStartsWith
        if package is not None:          conditions["package"]       = package

        if not conditions:
            raise ValueError(
                "Supported kwargs: text, resourceId, description, className, "
                "textContains, textStartsWith, package"
            )
        if len(conditions) == 1:
            by, value = next(iter(conditions.items()))
            return _U2JsonRpcElement(self, by, value)
        # Multi-condition: build combined selector with OR'd mask bits
        selector = self._build_multi_selector(conditions)
        first_by, first_value = next(iter(conditions.items()))
        return _U2JsonRpcElement(self, first_by, first_value, selector=selector)

    def wait_activity(self, activity: str, timeout: float = 10.0) -> bool:
        """Wait until the foreground package contains `activity`.

        Note: deviceInfo does not expose the current Activity class name — only the
        package. This method matches against the package name, not the activity.
        For full activity matching, use adb shell dumpsys activity top instead.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cur = self.app_current()
            if activity in cur.get("package", ""):
                return True
            time.sleep(0.3)
        return False

    # ── Internal RPC ──────────────────────────────────────────────────────────

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
        with self._http_lock:
            r = self._session.post(url, json=payload, timeout=t)
            if not r.ok:
                raise RuntimeError(
                    f"JSON-RPC HTTP {r.status_code} for method={method!r}: {r.text[:200]!r}"
                )
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
        if by == "text":
            return {"mask": _MASK_TEXT, "text": value}
        if by == "textContains":
            return {"mask": _MASK_TEXT_CONTAINS, "textContains": value}
        if by == "textStartsWith":
            return {"mask": _MASK_TEXT_STARTSWITH, "textStartsWith": value}
        if by in ("resource-id", "id"):
            return {"mask": _MASK_RESOURCE_ID, "resourceId": value}
        if by in ("class name", "className"):
            return {"mask": _MASK_CLASS_NAME, "className": value}
        if by in ("content-desc", "accessibility id", "description"):
            return {"mask": _MASK_DESCRIPTION, "description": value}
        if by == "package":
            return {"mask": _MASK_PACKAGE_NAME, "packageName": value}
        return {"mask": _MASK_TEXT, "text": value}

    @staticmethod
    def _build_multi_selector(conditions: Dict[str, str]) -> Dict[str, Any]:
        """Combine multiple by/value pairs into a single uiautomator2 selector.

        Each condition's mask bit is OR'd together so the server treats them as
        AND conditions (all must match simultaneously).
        """
        _FIELD_MAP: Dict[str, tuple] = {
            "text":             ("text",        _MASK_TEXT),
            "textContains":     ("textContains", _MASK_TEXT_CONTAINS),
            "textMatches":      ("textMatches", _MASK_TEXT_MATCHES),
            "textStartsWith":   ("textStartsWith", _MASK_TEXT_STARTSWITH),
            "resource-id":      ("resourceId",  _MASK_RESOURCE_ID),
            "id":               ("resourceId",  _MASK_RESOURCE_ID),
            "className":        ("className",   _MASK_CLASS_NAME),
            "class name":       ("className",   _MASK_CLASS_NAME),
            "description":      ("description", _MASK_DESCRIPTION),
            "content-desc":     ("description", _MASK_DESCRIPTION),
            "accessibility id": ("description", _MASK_DESCRIPTION),
            "package":          ("packageName", _MASK_PACKAGE_NAME),
        }
        _BOOL_MAP = {
            "checkable": _MASK_CHECKABLE,
            "checked": _MASK_CHECKED,
            "clickable": _MASK_CLICKABLE,
            "scrollable": _MASK_SCROLLABLE,
            "enabled": _MASK_ENABLED,
            "focused": _MASK_FOCUSED,
            "selected": _MASK_SELECTED,
        }
        mask = 0
        sel: Dict[str, Any] = {}
        for key, value in conditions.items():
            if key in _BOOL_MAP and isinstance(value, bool):
                if value:
                    sel[key] = True
                    mask |= _BOOL_MAP[key]
                continue
            if key in ("instance", "index"):
                try:
                    sel[key] = int(value)
                    mask |= _MASK_INSTANCE if key == "instance" else _MASK_INDEX
                except (TypeError, ValueError):
                    pass
                continue
            if key in _FIELD_MAP:
                field, m = _FIELD_MAP[key]
                sel[field] = value
                mask |= m
        sel["mask"] = mask
        return sel

    def _find_with_selector(self, selector: Dict[str, Any],
                            timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Find element by pre-built selector dict; return info+bounds dict or None."""
        wait_secs = timeout if timeout is not None else self._implicitly_wait
        if wait_secs > 0:
            wait_ms = int(wait_secs * 1000)
            try:
                found = self._rpc("waitForExists", selector, wait_ms,
                                  _timeout=wait_secs + 5.0)
                if not found:
                    return None
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "uiobjectnotfound" in msg or "json-rpc error" in msg:
                    return None
                raise
        try:
            info = self._rpc("objInfo", selector)
            if not info:
                return None
            raw_bounds = info.get("bounds") or info.get("visibleBounds")
            bounds = self._parse_bounds(raw_bounds)
            return {"bounds": bounds, "info": info}
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "uiobjectnotfound" in msg or "json-rpc error" in msg:
                return None
            raise

    def _wait_with_selector(self, selector: Dict[str, Any],
                            rpc_method: str, timeout: float) -> bool:
        """waitForExists / waitUntilGone on a pre-built selector dict."""
        wait_ms = int(timeout * 1000)
        try:
            result = self._rpc(rpc_method, selector, wait_ms,
                               _timeout=timeout + 5.0)
            return bool(result)
        except Exception:
            return False

    # ── Screen / power ────────────────────────────────────────────────────────

    def screen_on(self) -> None:
        """Wake the device screen."""
        try:
            self._rpc("screenOn")
        except Exception:
            self.press("power")

    def screen_off(self) -> None:
        """Put the device screen to sleep."""
        try:
            self._rpc("screenOff")
        except Exception:
            self.press("power")

    def unlock(self) -> None:
        """Unlock the device (dismiss keyguard)."""
        try:
            self._rpc("unlock")
        except Exception:
            # Fallback: wake then swipe-up to reveal unlock UI
            self.press("power")
            time.sleep(0.3)
            self.swipe_ext("up", scale=0.5, duration=0.4)

    # ── Extended gestures ─────────────────────────────────────────────────────

    def swipe_ext(self, direction: str, scale: float = 0.8,
                  duration: float = 0.5) -> None:
        """Swipe across the screen in a cardinal direction.

        direction: "up" | "down" | "left" | "right"
        scale:     fraction of the screen dimension to cover (default 0.8)
        duration:  gesture time in seconds
        """
        info = self.device_info
        w = info.get("displayWidth", 1080)
        h = info.get("displayHeight", 1920)
        cx, cy = w // 2, h // 2
        hw = int(w * scale / 2)
        hh = int(h * scale / 2)
        d = direction.lower()
        if d == "up":
            x1, y1, x2, y2 = cx, cy + hh, cx, cy - hh
        elif d == "down":
            x1, y1, x2, y2 = cx, cy - hh, cx, cy + hh
        elif d == "left":
            x1, y1, x2, y2 = cx + hw, cy, cx - hw, cy
        elif d == "right":
            x1, y1, x2, y2 = cx - hw, cy, cx + hw, cy
        else:
            raise ValueError(
                f"swipe_ext: unknown direction {direction!r}; use up/down/left/right"
            )
        self.swipe(x1, y1, x2, y2, duration)

    def scroll_to(self, by: str, value: str, direction: str = "up",
                  max_swipes: int = 10) -> bool:
        """Scroll until element (by, value) is visible on screen.

        Returns True if found within max_swipes, False otherwise.
        direction: which way to scroll to bring content into view (default "up").
        """
        for _ in range(max_swipes):
            if self.find_element(by, value, timeout=0) is not None:
                return True
            self.swipe_ext(direction, scale=0.6, duration=0.3)
            time.sleep(0.3)
        return self.find_element(by, value, timeout=0) is not None

    # ── APK install ───────────────────────────────────────────────────────────

    def install(self, apk_source: str, timeout: float = 90.0) -> None:
        """Install an APK via atx-agent's /install endpoint.

        apk_source: HTTP/HTTPS URL  → atx-agent downloads and installs it
                    local file path → uploaded as multipart then installed
        timeout:    total install timeout in seconds (default 90)

        Raises RuntimeError on failure.
        """
        install_url = self._base.rstrip("/") + "/install"
        with self._http_lock:
            if apk_source.startswith(("http://", "https://")):
                r = self._session.post(
                    install_url,
                    json={"url": apk_source},
                    timeout=timeout,
                )
            else:
                import os
                with open(apk_source, "rb") as fh:
                    r = self._session.post(
                        install_url,
                        files={
                            "file": (
                                os.path.basename(apk_source),
                                fh,
                                "application/vnd.android.package-archive",
                            )
                        },
                        timeout=timeout,
                    )
        if not r.ok:
            raise RuntimeError(
                f"install: HTTP {r.status_code}: {r.text[:200]!r}"
            )
        try:
            result = r.json()
        except Exception:
            return  # success with no JSON body
        if result.get("error") or result.get("success") is False:
            raise RuntimeError(f"install failed: {result.get('error') or result!r}")
