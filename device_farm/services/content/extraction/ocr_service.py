"""OCR extraction service — vi+en (DF-T-06-004)."""
from __future__ import annotations

import io
import logging
import time
from typing import Any

from PIL import Image

from services.content.extraction.models import OCRError, OCRExtractResult
from services.content.retry import with_extraction_retry

log = logging.getLogger(__name__)

_MAX_HEIGHT = 2400
_DEFAULT_CONFIDENCE = 0.5
_LANG_MAP = {"vi": "vie", "en": "eng", "vie": "vie", "eng": "eng"}


def _tesseract_lang(languages: list[str]) -> str:
    parts = []
    for lang in languages:
        code = _LANG_MAP.get(lang.lower(), lang.lower())
        if code not in parts:
            parts.append(code)
    return "+".join(parts) if parts else "eng"


def _maybe_resize(image_bytes: bytes, max_height: int = _MAX_HEIGHT) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    if img.height <= max_height:
        return image_bytes
    log.warning("image_too_large_resized height=%s -> %s", img.height, max_height)
    ratio = max_height / img.height
    resized = img.resize((int(img.width * ratio), max_height), Image.LANCZOS)
    out = io.BytesIO()
    resized.save(out, format="PNG")
    return out.getvalue()


def _normalize_region(region: dict[str, float] | tuple | None) -> dict[str, float] | None:
    if region is None:
        return None
    if isinstance(region, (tuple, list)) and len(region) == 4:
        x, y, w, h = region
        return {"x": x, "y": y, "w": w, "h": h}
    return region


def _to_bbox(entry: dict[str, Any]) -> dict[str, int]:
    conf_raw = entry.get("conf", entry.get("confidence", 0))
    conf = float(conf_raw)
    if conf > 1:
        conf /= 100.0
    return {
        "text": str(entry.get("text", "")).strip(),
        "bbox": {
            "x": int(entry.get("left", entry.get("x", 0))),
            "y": int(entry.get("top", entry.get("y", 0))),
            "w": int(entry.get("width", entry.get("w", 0))),
            "h": int(entry.get("height", entry.get("h", 0))),
        },
        "confidence": conf,
        "lang": entry.get("lang"),
    }


class OCRService:
    """Epic 06 OCR wrapper over runtime OCREngine."""

    def __init__(self, *, confidence_threshold: float = _DEFAULT_CONFIDENCE) -> None:
        self._confidence_threshold = confidence_threshold

    async def extract(
        self,
        image: bytes,
        *,
        lang: list[str] | None = None,
        region: dict[str, float] | tuple | None = None,
        confidence_threshold: float | None = None,
    ) -> OCRExtractResult:
        languages = lang or ["vi", "en"]
        threshold = confidence_threshold if confidence_threshold is not None else self._confidence_threshold
        started = time.perf_counter()

        async def _run() -> OCRExtractResult:
            from runtime.extraction.ocr_engine import OCREngine

            engine = OCREngine()
            if not engine.available:
                raise OCRError("OCR engine unavailable", code="ENGINE_UNAVAILABLE")

            payload = _maybe_resize(image)
            tess_lang = _tesseract_lang(languages)
            norm_region = _normalize_region(region)
            # OCREngine region uses normalized x1/y1/x2/y2
            ocr_region = None
            if norm_region and {"x", "y", "w", "h"}.issubset(norm_region):
                ocr_region = {
                    "x1": norm_region["x"],
                    "y1": norm_region["y"],
                    "x2": norm_region["x"] + norm_region["w"],
                    "y2": norm_region["y"] + norm_region["h"],
                }

            import asyncio

            loop = asyncio.get_running_loop()
            boxes = await loop.run_in_executor(
                None,
                lambda: engine.extract_with_boxes(
                    payload,
                    language=tess_lang,
                    region=ocr_region,
                    min_confidence=threshold,
                ),
            )

            high: list[dict[str, Any]] = []
            low: list[dict[str, Any]] = []
            for raw in boxes:
                item = _to_bbox(raw)
                if not item["text"]:
                    continue
                if item["confidence"] >= threshold:
                    high.append(item)
                else:
                    low.append(item)

            elapsed_ms = (time.perf_counter() - started) * 1000
            try:
                from web.metrics import ocr_latency_ms

                ocr_latency_ms.observe(elapsed_ms)
            except Exception:
                pass
            return OCRExtractResult(results=high, low_confidence_results=low, latency_ms=elapsed_ms)

        try:
            return await with_extraction_retry(_run, engine="ocr")
        except OCRError:
            raise
        except Exception as exc:
            raise OCRError(str(exc), code="ENGINE_ERROR") from exc
