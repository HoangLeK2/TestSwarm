from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Iterator, Optional

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

    Thread safety: uses a dedicated HTTP session separate from the main
    client session so watcher polling never races with main-thread RPCs.
    """

    def __init__(self, client: "U2JsonRpcClient") -> None:
        self._client = client
        self._entries: Dict[str, _WatcherEntry] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._interval = 2.0
        # Dedicated session — never shared with the main client session.
        self._session = requests.Session()
        self._session.headers.update({"Accept-Encoding": ""})

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
                self._client.click(cx, cy)
        elif action[0] == "press":
            self._client.press(action[1])

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
        """Fetch UI hierarchy using the dedicated watcher session."""
        payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "dumpWindowHierarchy",
            "params": [False, 50],
        }
        try:
            r = self._session.post(
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

    def drag_to(self, x: int, y: int, duration: float = 0.5) -> None:
        """Drag this element to absolute screen coordinates (x, y)."""
        selector = self._client._build_selector(self._by, self._value)
        steps = max(1, int(duration * 20))
        t = self._client._touch_timeout + duration
        self._client._rpc("objDrag", selector, int(x), int(y), steps, _timeout=t)

    def pinch_in(self, percent: int = 50, steps: int = 10) -> None:
        """Pinch in on this element (zoom out). percent: how far to pinch (0-100)."""
        selector = self._client._build_selector(self._by, self._value)
        self._client._rpc(
            "pinchIn", selector, percent, steps,
            _timeout=self._client._touch_timeout + steps * 0.05,
        )

    def pinch_out(self, percent: int = 50, steps: int = 10) -> None:
        """Pinch out on this element (zoom in). percent: how far to stretch (0-100)."""
        selector = self._client._build_selector(self._by, self._value)
        self._client._rpc(
            "pinchOut", selector, percent, steps,
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
            r = self._session.get(self._base + "/ping", timeout=t)
            return r.status_code == 200
        except Exception:
            return False

    def screenshot(self, timeout: float = 10.0, max_width: int = 800, quality: int = 70) -> Optional[bytes]:
        """
        Capture screenshot via u2 HTTP API (GET /screenshot/0).
        Returns JPEG bytes, resized to max_width if needed.
        Returns None on failure.
        """
        try:
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

    # ── Key events ────────────────────────────────────────────────────────────

    _KEYCODES: Dict[str, int] = {
        "home": 3, "back": 4, "menu": 82, "power": 26,
        "enter": 66, "del": 67, "delete": 67, "tab": 61,
        "recent": 187, "app_switch": 187,
        "volumeup": 24, "volumedown": 25,
    }

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
                            timeout: Optional[float] = None) -> Optional[str]:
        """Resolve xpath by dumping hierarchy XML and searching with ElementTree."""
        xpath_query = self._normalize_et_xpath(xpath_expr)
        wait = timeout if timeout is not None else self._implicitly_wait
        # Single check when timeout=0
        single_shot = wait <= 0
        deadline = time.monotonic() + max(wait, 0)
        while True:
            try:
                xml = self.page_source(timeout=self._timeout)
                if xml:
                    root = parse_xml(xml)
                    if root.findall(xpath_query):
                        return f"xpath::{xpath_expr}"
            except Exception as exc:
                logger.debug("xpath find failed for %r: %s", xpath_expr, exc)
                # Don't abort — stale/empty hierarchy is transient; retry after delay
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
        xpath_query = self._normalize_et_xpath(xpath_expr)
        try:
            xml = self.page_source(timeout=self._timeout)
            if not xml:
                return None
            root = parse_xml(xml)
            matches = root.findall(xpath_query)
            if not matches:
                return None
            node = matches[0]
            bounds_str = node.get("bounds", "")
            nums = [int(n) for n in re.findall(r"-?\d+", bounds_str)]
            bounds = {"left": nums[0], "top": nums[1], "right": nums[2], "bottom": nums[3]} if len(nums) == 4 else None
            return {"eid": f"xpath::{xpath_expr}", "bounds": bounds}
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

    def app_start(self, package: str, activity: Optional[str] = None) -> None:
        """Launch an app via `adb shell am start`.

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
        if activity:
            component = f"{package}/{activity}"
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
        self._rpc("stopPackage", package)

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
        # Fallback: IME-based injection (setFastInputText / sendKeys)
        for method in ("setFastInputText", "sendKeys"):
            try:
                self._rpc(method, text)
                return
            except Exception:
                pass
        # Last resort: setText with null selector (original behaviour)
        self._rpc("setText", None, text)

    def clear_text(self) -> None:
        focused_selector = {"mask": _MASK_FOCUSED, "focused": True}
        try:
            info = self._rpc("objInfo", focused_selector)
            if info:
                self._rpc("clearTextField", focused_selector, 0, 9999)
                return
        except Exception:
            pass
        self._rpc("clearTextField", None, 0, 9999)

    # ── Element builder ───────────────────────────────────────────────────────

    def xpath(self, xpath: str) -> _U2JsonRpcElement:
        return _U2JsonRpcElement(self, "xpath", xpath)

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
        if text is not None:
            return _U2JsonRpcElement(self, "text", text)
        if resourceId is not None:
            return _U2JsonRpcElement(self, "resource-id", resourceId)
        if description is not None:
            return _U2JsonRpcElement(self, "description", description)
        if className is not None:
            return _U2JsonRpcElement(self, "className", className)
        if textContains is not None:
            return _U2JsonRpcElement(self, "textContains", textContains)
        if textStartsWith is not None:
            return _U2JsonRpcElement(self, "textStartsWith", textStartsWith)
        if package is not None:
            return _U2JsonRpcElement(self, "package", package)
        raise ValueError(
            "Supported kwargs: text, resourceId, description, className, "
            "textContains, textStartsWith, package"
        )

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
