"""OCR on the relay — engine wrapper and the ocr message handler.

Background: media now goes media-adapter → go2rtc, so the farm's scrcpy JPEG
cache is never filled and it has no frame of its own to read. OCR therefore runs
here, on the host that already has the pixels, and only text goes back.
"""
from __future__ import annotations

import asyncio
import base64
import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from relay import ocr as ocr_engine
from relay.agent import RelayAgent
from relay.runtime import init_executors, init_semaphores, loads


def _text_image(*lines: tuple[str, int], size: tuple[int, int] = (600, 300)) -> bytes:
    img = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except (OSError, IOError):
        font = ImageFont.load_default()
    for text, top in lines:
        draw.text((20, top), text, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


requires_tesseract = pytest.mark.skipif(
    not ocr_engine.available(), reason="tesseract not installed"
)


class TestOcrEngine:
    def test_lang_mapping(self):
        assert ocr_engine.tesseract_lang(["vi", "en"]) == "vie+eng"
        assert ocr_engine.tesseract_lang("eng") == "eng"
        # The farm's default is Vietnamese + English; an empty list must not
        # silently narrow that to English only.
        assert ocr_engine.tesseract_lang(None) == "vie+eng"
        assert ocr_engine.tesseract_lang(["vi", "vie"]) == "vie"

    @requires_tesseract
    def test_reads_text(self):
        boxes = ocr_engine.run_ocr(_text_image(("Hello Farm", 40)), languages=["en"])
        assert boxes, "no boxes for an image that clearly has text"
        assert "hello" in " ".join(b["text"] for b in boxes).lower()

    @requires_tesseract
    def test_region_boxes_are_in_original_coordinates(self):
        """A cropped read must still report where the text is on screen.

        Reporting crop-local coordinates would silently mislocate every box by
        the crop offset.
        """
        image = _text_image(("Top Line", 20), ("Bottom Line", 200))
        boxes = ocr_engine.run_ocr(
            image, languages=["en"], region={"x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 1.0}
        )
        assert boxes
        joined = " ".join(b["text"] for b in boxes).lower()
        assert "bottom" in joined
        assert "top" not in joined
        assert min(b["top"] for b in boxes) >= 150

    @requires_tesseract
    def test_out_of_bounds_region_does_not_shift_boxes(self):
        """The crop origin must be the clamped one, not the requested one.

        A region starting before the image edge gets clamped to 0 by the crop;
        offsetting boxes by the unclamped value would shift every result.
        """
        image = _text_image(("Edge", 20), size=(400, 200))
        boxes = ocr_engine.run_ocr(
            image, languages=["en"], region={"x1": -0.5, "y1": -0.5, "x2": 1.0, "y2": 1.0}
        )
        assert boxes
        assert all(b["left"] >= 0 and b["top"] >= 0 for b in boxes)

    def test_bad_input_returns_empty_not_raises(self):
        # A blank screen is a normal result, so callers should not have to guard
        # against exceptions for it.
        assert ocr_engine.run_ocr(b"") == []
        assert ocr_engine.run_ocr(b"not-an-image") == []


class _FakeU2Executor:
    """Stands in for U2Executor.run_batch's screenshot op."""

    def __init__(self, *, ok: bool = True, value: str | None = None) -> None:
        self.ok, self.value = ok, value
        self.calls: list[list[dict]] = []

    async def run_batch(self, *, serial, actions, **kwargs):
        self.calls.append(actions)
        if not self.ok:
            return {
                "ok": False,
                "results": [{"ok": False, "error": "device offline"}],
                "error": "device offline",
            }
        return {"ok": True, "results": [{"ok": True, "value": self.value, "error": None}]}


def _agent(u2) -> RelayAgent:
    agent = RelayAgent.__new__(RelayAgent)
    agent._u2_executor = u2
    agent._ocr_tasks = {}
    agent._ocr_cancel_events = {}
    return agent


async def _handle(agent, **overrides):
    init_executors()
    init_semaphores()
    queue: asyncio.Queue = asyncio.Queue()
    msg = {"type": "ocr", "id": "req-1", "serial": "dev-1"}
    cancel = overrides.pop("cancel_event", None)
    msg.update(overrides)
    await agent._handle_ocr(msg, queue, cancel)
    return loads(await queue.get())


class TestOcrHandler:
    @requires_tesseract
    async def test_returns_text_without_the_screenshot(self):
        shot = base64.b64encode(_text_image(("Hello Farm", 40))).decode()
        u2 = _FakeU2Executor(value=shot)
        reply = await _handle(_agent(u2))

        assert reply["ok"] is True
        assert reply["count"] > 0
        # The whole point of moving OCR here: pixels stay on the host.
        assert "image_b64" not in reply
        assert u2.calls == [[{"op": "screenshot"}]]

    @requires_tesseract
    async def test_ships_frame_only_when_read_came_back_empty(self):
        blank = base64.b64encode(_text_image(size=(400, 200))).decode()

        reply = await _handle(_agent(_FakeU2Executor(value=blank)), want_image_on_empty=True)
        assert reply["count"] == 0
        assert reply.get("image_b64"), "empty read is exactly when a picture is needed"

        reply = await _handle(_agent(_FakeU2Executor(value=blank)), want_image_on_empty=False)
        assert reply["count"] == 0
        assert "image_b64" not in reply

    async def test_screenshot_failure_is_reported(self):
        reply = await _handle(_agent(_FakeU2Executor(ok=False)))
        assert reply["ok"] is False
        assert "device offline" in reply["error"]

    async def test_missing_serial(self):
        reply = await _handle(_agent(_FakeU2Executor()), serial="")
        assert reply["ok"] is False
        assert reply["error"] == "serial_required"

    async def test_cancelled_before_ocr(self):
        shot = base64.b64encode(_text_image(("Hello", 40))).decode()
        event = asyncio.Event()
        event.set()
        reply = await _handle(_agent(_FakeU2Executor(value=shot)), cancel_event=event)
        assert reply["ok"] is False
        assert reply["cancelled"] is True

    async def test_reports_unavailable_engine_instead_of_hanging(self, monkeypatch):
        monkeypatch.setattr(ocr_engine, "available", lambda: False)
        reply = await _handle(_agent(_FakeU2Executor()))
        assert reply["ok"] is False
        assert reply["error"] == "ocr_engine_unavailable"
