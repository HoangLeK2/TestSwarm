"""Hierarchy, flat UI elements, selector tap, hit-test."""

from __future__ import annotations

import asyncio
import logging
import re
from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from api.schemas.device_control import HitTestRequest, TapSelectorRequest
from runtime.core import DeviceManager
from runtime.xml_utils import XML_PARSE_ERRORS, parse_xml

_LOG = logging.getLogger(__name__)
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


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

        for node in root.iter():
            text = (node.get("text") or "").strip()
            rid = (node.get("resource-id") or "").strip()
            desc = (node.get("content-desc") or "").strip()
            cls = (node.get("class") or "").strip()
            clickable = node.get("clickable") == "true"
            bounds_str = node.get("bounds") or ""
            m = _BOUNDS_RE.search(bounds_str)
            bounds = [int(m.group(i)) for i in range(1, 5)] if m else None

            if not text and not rid and not desc:
                continue

            sel_by, sel_val = _best_selector(text, rid, desc)
            elements.append({
                "text": text or None,
                "resource_id": rid or None,
                "content_desc": desc or None,
                "class_name": cls.split(".")[-1] if cls else None,
                "bounds": bounds,
                "clickable": clickable,
                "selector_by": sel_by,
                "selector_value": sel_val,
            })

        seen: set[tuple] = set()
        unique: list[dict] = []
        duplicates: int = 0
        for el in elements:
            key = (el["selector_by"], el["selector_value"])
            if key not in seen:
                seen.add(key)
                unique.append(el)
            else:
                duplicates += 1

        return {
            "serial": serial,
            "element_count": len(unique),
            "duplicates_hidden": duplicates,
            "elements": unique,
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
