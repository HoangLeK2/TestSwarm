"""OCR extraction service — vi+en (DF-T-06-004).

OCR runs on agent-boot, not here. Media goes media-adapter → go2rtc without
passing through the farm, so ``DeviceClient.take_screenshot()`` — which only
reads the scrcpy JPEG cache — has nothing to return, and the farm has no frame
of its own to read. The agent screenshots and OCRs on the host that already has
the pixels, and sends back text: ~3.6 KB per call instead of ~630 KB.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

from services.content.extraction.models import OCRError, OCRExtractResult

log = logging.getLogger(__name__)

_DEFAULT_CONFIDENCE = 0.5
_DEFAULT_LANGS = ["vi", "en"]


def _normalize_region(region: dict[str, float] | tuple | None) -> dict[str, float] | None:
    if region is None:
        return None
    if isinstance(region, (tuple, list)) and len(region) == 4:
        x, y, w, h = region
        return {"x": x, "y": y, "w": w, "h": h}
    return region


def compose_text(results: list[dict[str, Any]]) -> str:
    """Join OCR boxes back into readable lines.

    Tesseract returns one box per *word*, so joining every box with a newline
    turns a headline into a column of single words — unreadable in the editor,
    and worse, no downstream `contains "some phrase"` can ever match because the
    words are separated by newlines instead of spaces.

    Boxes on the same visual line are detected by vertical overlap of their
    centres rather than an equal `y`: word baselines within one line differ by a
    few pixels, and the tolerance has to scale with font size, so it is derived
    from the median box height instead of being a fixed constant.
    """
    boxes = [b for b in results if (b.get("text") or "").strip()]
    if not boxes:
        return ""

    def centre_y(box: dict[str, Any]) -> float:
        bbox = box.get("bbox") or {}
        return float(bbox.get("y", 0)) + float(bbox.get("h", 0)) / 2

    def left_x(box: dict[str, Any]) -> float:
        return float((box.get("bbox") or {}).get("x", 0))

    heights = sorted(float((b.get("bbox") or {}).get("h", 0)) for b in boxes)
    median_h = heights[len(heights) // 2] or 0.0
    # Half a line height: tall enough to absorb baseline jitter, short enough
    # that the next line down never merges into the current one.
    tolerance = median_h * 0.5 if median_h else 0.0

    lines: list[list[dict[str, Any]]] = []
    for box in sorted(boxes, key=lambda b: (centre_y(b), left_x(b))):
        if lines and abs(centre_y(box) - centre_y(lines[-1][-1])) <= tolerance:
            lines[-1].append(box)
        else:
            lines.append([box])

    return "\n".join(
        " ".join((b.get("text") or "").strip() for b in sorted(line, key=left_x))
        for line in lines
    )


def _to_bbox(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalise one agent box.

    Produced by ``relay/ocr.py::run_ocr`` — left/top/width/height with ``conf``
    as a 0-100 percentage. Keep the two in step.
    """
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
    """Epic 06 OCR wrapper over the agent-boot OCR relay."""

    def __init__(self, *, confidence_threshold: float = _DEFAULT_CONFIDENCE) -> None:
        self._confidence_threshold = confidence_threshold

    async def extract_on_device(
        self,
        device: Any,
        *,
        lang: list[str] | None = None,
        region: dict[str, float] | tuple | None = None,
        confidence_threshold: float | None = None,
        want_image_on_empty: bool = False,
        timeout: float = 30.0,
    ) -> tuple[OCRExtractResult, bytes | None]:
        """Run OCR on the agent. Returns the result plus a screenshot iff empty.

        The image only comes back when the read found nothing — that is the case
        an operator needs a picture for. Shipping it every time would put ~630 KB
        per step back on the wire, which is the whole reason OCR moved.
        """
        languages = lang or list(_DEFAULT_LANGS)
        threshold = confidence_threshold if confidence_threshold is not None else self._confidence_threshold
        started = time.perf_counter()

        if not getattr(device, "ocr_supported", None) or not device.ocr_supported():
            raise OCRError(
                f"agent for device {getattr(device, 'serial', '?')} has no OCR engine "
                "(update agent-boot; its image needs tesseract)",
                code="OCR_AGENT_UNSUPPORTED",
            )

        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(
            None,
            lambda: device.request_ocr(
                languages=languages,
                region=_normalize_region(region),
                min_confidence=threshold,
                want_image_on_empty=want_image_on_empty,
                timeout=timeout,
            ),
        )
        if not reply.get("ok"):
            raise OCRError(
                str(reply.get("error") or "agent OCR failed"),
                code="OCR_AGENT_ERROR",
            )

        # The agent already dropped everything below `threshold`, so re-bucketing
        # here would only ever produce an empty low-confidence list. Anything
        # that comes back is above the bar by construction.
        results = [
            item for item in (_to_bbox(raw) for raw in reply.get("results") or [])
            if item["text"]
        ]

        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            from web.metrics import ocr_latency_ms

            ocr_latency_ms.observe(elapsed_ms)
        except Exception:
            pass

        image: bytes | None = None
        raw_b64 = reply.get("image_b64")
        if raw_b64:
            try:
                image = base64.b64decode(raw_b64)
            except Exception:
                image = None
        return (
            OCRExtractResult(results=results, latency_ms=elapsed_ms),
            image,
        )
