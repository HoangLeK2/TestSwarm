"""DF-009 / Epic 06: Extraction API — hierarchy + OCR (AI vision unchanged)."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from runtime.core import DeviceManager
from services.content.extraction.capture_service import ExtractionCaptureService
from services.content.extraction.hierarchy.service import HierarchyService
from services.content.extraction.models import CaptureError, OCRError, StrategyMismatchError, StrategyNotFoundError
from services.content.extraction.ocr_service import OCRService

log = logging.getLogger(__name__)


class HierarchyExtractBody(BaseModel):
    filter_class: list[str] | None = None
    exclude_empty: bool = True
    format: str = "text"  # "text" or "json"
    strategy: str = "screen_data"


class OCRExtractBody(BaseModel):
    languages: list[str] = Field(default_factory=lambda: ["vi", "en"])
    region: dict[str, float] | None = None
    confidence_threshold: float = 0.5


class AIExtractBody(BaseModel):
    prompt: str
    provider: str = "openai"
    format: str = "json"
    model: str | None = None
    region: dict[str, float] | None = None


def build_extraction_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter(tags=["extraction"])
    capture = ExtractionCaptureService()
    hierarchy = HierarchyService(capture)
    ocr = OCRService()

    @router.post("/devices/{serial}/extract/hierarchy")
    async def api_extract_hierarchy(serial: str, body: HierarchyExtractBody):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)

        try:
            if body.format == "json" and body.strategy:
                result = await hierarchy.extract(
                    device,
                    body.strategy,
                    config={
                        "filter_class": body.filter_class,
                        "exclude_empty": body.exclude_empty,
                    },
                    persist=False,
                )
                items = result.data if isinstance(result.data, list) else [result.data]
                return {
                    "items": items,
                    "count": len(items),
                    "strategy": result.strategy_name,
                    "latency_ms": result.latency_ms,
                    "node_count": result.node_count,
                }

            loop = asyncio.get_running_loop()
            handle = await loop.run_in_executor(
                None,
                lambda: capture.capture_hierarchy(device, persist=False),
            )
            from runtime.extraction.hierarchy_extractor import HierarchyExtractor

            xml = handle.xml_bytes.decode("utf-8")
            items = HierarchyExtractor.extract_texts(
                xml,
                filter_class=body.filter_class,
                exclude_empty=body.exclude_empty,
            )
            if body.format == "json":
                return {"items": items, "count": len(items)}
            text = "\n".join(i["text"] for i in items if i.get("text"))
            return {"text": text, "count": len(items)}
        except StrategyNotFoundError as exc:
            return JSONResponse(
                {"error_code": "STRATEGY_NOT_FOUND", "strategy": exc.strategy, "available": exc.available},
                status_code=422,
            )
        except StrategyMismatchError as exc:
            return JSONResponse(
                {"error_code": "STRATEGY_MISMATCH", "reason": exc.reason, "details": exc.details},
                status_code=422,
            )
        except CaptureError as exc:
            return JSONResponse({"error_code": exc.code, "details": exc.details}, status_code=422)

    @router.post("/devices/{serial}/extract/ocr")
    async def api_extract_ocr(serial: str, body: OCRExtractBody):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)

        try:
            # OCR happens on agent-boot: since media moved to go2rtc the farm has
            # no frame of its own, and this keeps the screenshot off the wire.
            result, _image = await ocr.extract_on_device(
                device,
                lang=body.languages,
                region=body.region,
                confidence_threshold=body.confidence_threshold,
            )
            return {
                "results": result.results,
                "low_confidence_results": result.low_confidence_results,
                "count": len(result.results),
                "latency_ms": result.latency_ms,
            }
        except CaptureError as exc:
            return JSONResponse({"error_code": exc.code, "details": exc.details}, status_code=422)
        except OCRError as exc:
            return JSONResponse(
                {"error_code": exc.code, "partial_results": exc.partial_results},
                status_code=503,
            )

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
