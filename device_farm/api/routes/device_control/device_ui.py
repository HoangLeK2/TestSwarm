"""Hierarchy, flat UI elements, selector tap, hit-test."""

from __future__ import annotations

import asyncio
import logging
import re
from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from api.schemas.device_control import HitTestRequest, TapSelectorRequest
from api.routes.device_control.guards import reject_manual_control_if_busy
from runtime.core import DeviceManager
from runtime.xml_utils import XML_PARSE_ERRORS, parse_xml

_LOG = logging.getLogger(__name__)
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_SYSTEM_UI_PACKAGE_PREFIXES = (
    "com.android.systemui",
    "com.android.providers.",
    "com.android.permissioncontroller",
)
_CONTAINER_CLASSES = {
    "android.widget.FrameLayout",
    "android.widget.LinearLayout",
    "android.widget.RelativeLayout",
    "android.view.View",
    "android.view.ViewGroup",
    "android.widget.ScrollView",
    "androidx.recyclerview.widget.RecyclerView",
    "androidx.constraintlayout.widget.ConstraintLayout",
    "android.widget.HorizontalScrollView",
    "androidx.viewpager.widget.ViewPager",
}


def _best_selector(text: str, rid: str, desc: str):
    if text and len(text) < 80:
        return "text", text
    if rid and "/" in rid:
        return "resource-id", rid
    if desc and len(desc) < 80:
        return "description", desc
    if rid:
        return "resource-id", rid
    return None, None


def _is_system_ui_package(pkg: str) -> bool:
    pkg = (pkg or "").strip()
    if not pkg or pkg == "android":
        return True
    return any(pkg == prefix or pkg.startswith(prefix) for prefix in _SYSTEM_UI_PACKAGE_PREFIXES)


def _is_generic_resource_id(resource_id: str) -> bool:
    rid = (resource_id or "").strip()
    if not rid:
        return True
    if "(name removed)" in rid:
        return True
    return bool(re.search(r":id/(list|content|root|container|main_layout)$", rid, re.I))


def _build_bounds_xpath(bounds_str: str) -> str | None:
    bounds = (bounds_str or "").strip()
    if not _BOUNDS_RE.fullmatch(bounds):
        return None
    return f'//*[@bounds="{bounds}"]'


def _parse_bounds(bounds_str: str) -> list[int] | None:
    m = _BOUNDS_RE.search(bounds_str or "")
    return [int(m.group(i)) for i in range(1, 5)] if m else None


def _infer_screen_dims(nodes) -> tuple[int, int]:
    max_right = 0
    max_bottom = 0
    for node in nodes:
        bounds = _parse_bounds(node.get("bounds") or "")
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            continue
        max_right = max(max_right, x2)
        max_bottom = max(max_bottom, y2)
    return max_right or 1080, max_bottom or 1920


def _select_node_selector(
    *,
    text: str,
    rid: str,
    desc: str,
    cls: str,
    bounds_str: str,
    rid_count: int,
    text_count: int,
    desc_count: int,
) -> tuple[str | None, str | None, str, bool]:
    text_ok = bool(text) and len(text) < 500
    desc_ok = bool(desc) and len(desc) < 500
    rid_ok = bool(rid) and not _is_generic_resource_id(rid)
    cls_is_container = cls in _CONTAINER_CLASSES

    if rid_ok and rid_count == 1:
        return "resource-id", rid, "unique resource-id", False
    if desc_ok and desc_count == 1:
        return "description", desc, "unique content-desc", False
    if text_ok and text_count == 1:
        return "text", text, "unique text", False

    xpath = _build_bounds_xpath(bounds_str)
    if xpath:
        return "xpath", xpath, "bounds fallback", True

    if cls and not cls_is_container:
        return "class name", cls, "class fallback", True
    if rid_ok:
        return "resource-id", rid, "duplicate resource-id fallback", True
    if desc_ok:
        return "description", desc, "duplicate content-desc fallback", True
    if text_ok:
        return "text", text, "duplicate text fallback", True
    return None, None, "no stable selector", True


def build_device_ui_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter()

    @router.get("/devices/{serial}/hierarchy")
    async def api_hierarchy(serial: str, refresh: bool = False):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        xml_str = await loop.run_in_executor(
            None, lambda: device.hierarchy_xml(force_refresh=refresh)
        )
        if not xml_str:
            return JSONResponse(
                {"error": "Hierarchy not available (uiautomator2 not connected or dump failed)"},
                status_code=503,
            )
        return PlainTextResponse(xml_str, media_type="application/xml")

    @router.get("/devices/{serial}/ui_elements")
    async def api_ui_elements(serial: str, refresh: bool = True):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        xml_str = await loop.run_in_executor(
            None, lambda: device.hierarchy_xml(force_refresh=refresh)
        )
        if not xml_str:
            return JSONResponse(
                {"error": "UI hierarchy not available — uiautomator2 not connected or dump failed"},
                status_code=503,
            )

        elements: list[dict] = []
        try:
            root = parse_xml(xml_str)
        except XML_PARSE_ERRORS as e:
            return JSONResponse({"error": f"XML parse error: {e}"}, status_code=500)

        all_nodes = list(root.iter())
        app_bound_nodes = [
            node
            for node in all_nodes
            if not _is_system_ui_package((node.get("package") or "").strip())
        ]
        screen_width, screen_height = _infer_screen_dims(app_bound_nodes or all_nodes)

        candidate_nodes = []
        for node in all_nodes:
            text = (node.get("text") or "").strip()
            rid = (node.get("resource-id") or "").strip()
            desc = (node.get("content-desc") or "").strip()

            if not text and not rid and not desc:
                continue
            candidate_nodes.append(node)

        has_app_nodes = any(
            not _is_system_ui_package((node.get("package") or "").strip())
            for node in candidate_nodes
        )
        if has_app_nodes:
            candidate_nodes = [
                node
                for node in candidate_nodes
                if not _is_system_ui_package((node.get("package") or "").strip())
            ]

        rid_count: dict[str, int] = {}
        text_count: dict[str, int] = {}
        desc_count: dict[str, int] = {}
        for node in candidate_nodes:
            rid = (node.get("resource-id") or "").strip()
            text = (node.get("text") or "").strip()
            desc = (node.get("content-desc") or "").strip()
            if rid:
                rid_count[rid] = rid_count.get(rid, 0) + 1
            if text and len(text) < 500:
                text_count[text] = text_count.get(text, 0) + 1
            if desc and len(desc) < 500:
                desc_count[desc] = desc_count.get(desc, 0) + 1

        for node in candidate_nodes:
            text = (node.get("text") or "").strip()
            rid = (node.get("resource-id") or "").strip()
            desc = (node.get("content-desc") or "").strip()
            cls = (node.get("class") or "").strip()
            pkg = (node.get("package") or "").strip()
            clickable = node.get("clickable") == "true"
            bounds_str = node.get("bounds") or ""
            bounds = _parse_bounds(bounds_str)
            fallback_rx = None
            fallback_ry = None
            if bounds and screen_width > 0 and screen_height > 0:
                x1, y1, x2, y2 = bounds
                fallback_rx = (x1 + x2) / 2 / screen_width
                fallback_ry = (y1 + y2) / 2 / screen_height

            sel_by, sel_val, selector_reason, selector_volatile = _select_node_selector(
                text=text,
                rid=rid,
                desc=desc,
                cls=cls,
                bounds_str=bounds_str,
                rid_count=rid_count.get(rid, 0),
                text_count=text_count.get(text, 0),
                desc_count=desc_count.get(desc, 0),
            )
            elements.append({
                "text": text or None,
                "resource_id": rid or None,
                "content_desc": desc or None,
                "class_name": cls.split(".")[-1] if cls else None,
                "package": pkg or None,
                "bounds": bounds,
                "clickable": clickable,
                "selector_by": sel_by,
                "selector_value": sel_val,
                "selector_reason": selector_reason,
                "selector_volatile": selector_volatile,
                "resource_id_duplicate_count": rid_count.get(rid, 0) if rid else 0,
                "text_duplicate_count": text_count.get(text, 0) if text else 0,
                "content_desc_duplicate_count": desc_count.get(desc, 0) if desc else 0,
                "fallback_rx": fallback_rx,
                "fallback_ry": fallback_ry,
                "screen_width": screen_width,
                "screen_height": screen_height,
            })

        seen: set[tuple] = set()
        duplicate_selectors: int = 0
        for el in elements:
            key = (el["selector_by"], el["selector_value"])
            if key in seen:
                duplicate_selectors += 1
            seen.add(key)

        return {
            "serial": serial,
            "element_count": len(elements),
            "duplicates_hidden": 0,
            "duplicate_selector_count": duplicate_selectors,
            "elements": elements,
            "usage": (
                "Pick element by text/resource_id/content_desc, "
                "then call POST /api/tap_selector/{serial} with {by: selector_by, value: selector_value}. "
                "If element_count < 5, XML may be flat (enable Accessibility Service on device)."
            ),
        }

    @router.post("/tap_selector/{serial}")
    async def api_tap_selector(serial: str, body: TapSelectorRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        if blocked := await reject_manual_control_if_busy(device):
            return blocked
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, device.tap_selector, body.by, body.value)
        except LookupError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"tap_selector failed: {e}"}, status_code=500)
        return {"ok": True}

    @router.post("/devices/{serial}/hit_test")
    async def api_hit_test(serial: str, body: HitTestRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        if body.rx >= 0 and body.ry >= 0:
            w = device.screen_width or 1080
            h = device.screen_height or 1920
            px = int(body.rx * w)
            py = int(body.ry * h)
        else:
            px, py = body.x, body.y

        loop = asyncio.get_running_loop()
        sel = await loop.run_in_executor(None, device.hit_test_selector, px, py)
        _LOG.info(
            "hit_test serial=%s rx=%s ry=%s → px=%s py=%s → sel=%s  u2=%s  sw=%s sh=%s  cache=%s",
            serial, body.rx, body.ry, px, py, sel,
            "ok" if getattr(device, "_u2", None) is not None else "None",
            getattr(device, "screen_width", None),
            getattr(device, "screen_height", None),
            "ok" if getattr(device, "_hierarchy_cache", None) else "None",
        )
        if not sel:
            return {"by": None, "value": None}
        return {"by": sel.get("by"), "value": sel.get("value")}

    return router
