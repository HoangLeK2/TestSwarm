"""DF-009: Extraction API — standalone OCR/AI/hierarchy text extraction."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from runtime.core import DeviceManager

log = logging.getLogger(__name__)


class HierarchyExtractBody(BaseModel):
    filter_class: list[str] | None = None
    exclude_empty: bool = True
    format: str = "text"  # "text" or "json"


class OCRExtractBody(BaseModel):
    language: str = "eng"
    region: dict[str, float] | None = None
    psm: int = 11
    scale_factor: float = 2.0


class AIExtractBody(BaseModel):
    prompt: str
    provider: str = "openai"
    format: str = "json"
    model: str | None = None
    region: dict[str, float] | None = None


def build_extraction_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter(tags=["extraction"])

    @router.post("/devices/{serial}/extract/hierarchy")
    async def api_extract_hierarchy(serial: str, body: HierarchyExtractBody):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)

        loop = asyncio.get_running_loop()
        xml = await loop.run_in_executor(None, lambda: device.hierarchy_xml(force_refresh=True))
        if not xml:
            return JSONResponse({"error": "No hierarchy available"}, status_code=422)

        from runtime.extraction.hierarchy_extractor import HierarchyExtractor
        items = HierarchyExtractor.extract_texts(
            xml,
            filter_class=body.filter_class,
            exclude_empty=body.exclude_empty,
        )

        if body.format == "json":
            return {"items": items, "count": len(items)}
        else:
            text = "\n".join(i["text"] for i in items if i.get("text"))
            return {"text": text, "count": len(items)}

    @router.post("/devices/{serial}/extract/ocr")
    async def api_extract_ocr(serial: str, body: OCRExtractBody):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)

        loop = asyncio.get_running_loop()
        frame = await loop.run_in_executor(None, device.take_screenshot)
        if not frame:
            return JSONResponse({"error": "No screenshot available"}, status_code=422)

        from runtime.extraction.ocr_engine import OCREngine
        ocr = OCREngine()
        if not ocr.available:
            return JSONResponse(
                {"error": "Tesseract not installed. Run: brew install tesseract"},
                status_code=503,
            )

        text = await loop.run_in_executor(
            None,
            lambda: ocr.extract_text(
                frame,
                language=body.language,
                region=body.region,
                psm=body.psm,
                scale_factor=body.scale_factor,
            ),
        )
        return {"text": text, "chars": len(text)}

    @router.post("/devices/{serial}/extract/ai")
    async def api_extract_ai(serial: str, body: AIExtractBody):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)

        loop = asyncio.get_running_loop()
        frame = await loop.run_in_executor(None, device.take_screenshot)
        if not frame:
            return JSONResponse({"error": "No screenshot available"}, status_code=422)

        from runtime.extraction.ai_vision import AIVisionExtractor
        ai = AIVisionExtractor()

        try:
            result = await loop.run_in_executor(
                None,
                lambda: ai.extract(
                    frame,
                    prompt=body.prompt,
                    provider=body.provider,
                    output_format=body.format,
                    model=body.model,
                    region=body.region,
                ),
            )
            return {"data": result}
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return router
