"""Template matching against the device screen, executed on agent-boot.

Same reasoning as OCR: media goes media-adapter -> go2rtc without passing
through the farm, so ``DeviceClient.take_screenshot()`` has nothing to return
and the backend has no frame to search. The agent screenshots and matches on the
host that already has the pixels, and sends back a coordinate.

Measured on real 1260x2800 screenshots: matching at the default 0.25 scale costs
~9 ms versus 115-265 ms at full resolution, with no loss of accuracy.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from services.content.extraction.models import OCRError

log = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.8
DEFAULT_SCALE = 0.25


@dataclass(slots=True)
class ImageMatchResult:
    found: bool
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    cx: int = 0
    cy: int = 0
    confidence: float = 0.0
    latency_ms: float = 0.0


class ImageMatchError(OCRError):
    """Template matching failed. Subclasses OCRError so step handlers that
    already catch extraction failures keep working unchanged."""


class ImageMatchService:
    """Locate a cropped template on a device screen via the agent."""

    def __init__(self, *, threshold: float = DEFAULT_THRESHOLD, scale: float = DEFAULT_SCALE) -> None:
        self._threshold = threshold
        self._scale = scale

    async def find(
        self,
        device: Any,
        template: bytes,
        *,
        threshold: float | None = None,
        scale: float | None = None,
        template_screen_w: int | None = None,
        timeout: float = 20.0,
    ) -> ImageMatchResult:
        if not template:
            raise ImageMatchError("template image is empty", code="IMAGE_TEMPLATE_EMPTY")

        supported = getattr(device, "image_match_supported", None)
        if not supported or not supported():
            raise ImageMatchError(
                f"agent for device {getattr(device, 'serial', '?')} cannot match images "
                "(update agent-boot; its image needs OpenCV)",
                code="IMAGE_MATCH_AGENT_UNSUPPORTED",
            )

        started = time.perf_counter()
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(
            None,
            lambda: device.request_image_match(
                template=template,
                threshold=threshold if threshold is not None else self._threshold,
                scale=scale if scale is not None else self._scale,
                template_screen_w=template_screen_w,
                timeout=timeout,
            ),
        )
        if not reply.get("ok"):
            raise ImageMatchError(
                str(reply.get("error") or "agent image match failed"),
                code="IMAGE_MATCH_AGENT_ERROR",
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        if not reply.get("found"):
            return ImageMatchResult(found=False, latency_ms=elapsed_ms)
        return ImageMatchResult(
            found=True,
            x=int(reply.get("x", 0)),
            y=int(reply.get("y", 0)),
            w=int(reply.get("w", 0)),
            h=int(reply.get("h", 0)),
            cx=int(reply.get("cx", 0)),
            cy=int(reply.get("cy", 0)),
            confidence=float(reply.get("conf", 0.0)),
            latency_ms=elapsed_ms,
        )
