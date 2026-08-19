"""Unit tests for DF-009: OCR & Screen Text Extraction.

Tests cover:
  - HierarchyExtractor: XML parsing, text extraction, filtering, bounds
  - OCREngine: preprocessing, extract_text, extract_with_boxes, region crop
  - AIVisionExtractor: markdown stripping, region crop, error handling
  - Scenario step handlers: extract_text_hierarchy, extract_text_ocr, extract_screen_data
"""
from __future__ import annotations

import io
import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from runtime.extraction.hierarchy_extractor import HierarchyExtractor, _parse_bounds
from runtime.extraction.ocr_engine import OCREngine
from runtime.extraction.ai_vision import AIVisionExtractor, _strip_markdown_json


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_HIERARCHY_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" resource-id="" content-desc="" bounds="[0,0][1080,2316]">
    <node index="0" text="Xin chào" class="android.widget.TextView" resource-id="com.app:id/title" content-desc="" bounds="[50,100][500,150]" />
    <node index="1" text="Đăng nhập" class="android.widget.Button" resource-id="com.app:id/btn_login" content-desc="Login button" bounds="[100,200][400,260]" />
    <node index="2" text="" class="android.widget.EditText" resource-id="com.app:id/input_email" content-desc="Email input" bounds="[50,300][500,360]" />
    <node index="3" text="" class="android.widget.ImageView" resource-id="com.app:id/logo" content-desc="" bounds="[200,50][400,90]" />
    <node index="4" text="12345" class="android.widget.TextView" resource-id="com.app:id/count" content-desc="" bounds="[600,100][700,150]" />
  </node>
</hierarchy>"""


def _make_test_image(width: int = 200, height: int = 100, text_color: int = 0) -> bytes:
    """Create a simple test image with solid background."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    # Draw some dark pixels to simulate text
    arr = np.array(img)
    arr[30:70, 20:180] = text_color  # black band
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_text_image(text: str = "Hello World", width: int = 400, height: int = 100) -> bytes:
    """Create image with actual text using PIL (for OCR testing)."""
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except (OSError, IOError):
        font = ImageFont.load_default()
    draw.text((20, 30), text, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── HierarchyExtractor ───────────────────────────────────────────────────────


class TestParseBounds:
    def test_valid_bounds(self):
        result = _parse_bounds("[50,100][500,150]")
        assert result == {"x1": 50, "y1": 100, "x2": 500, "y2": 150}

    def test_empty_string(self):
        assert _parse_bounds("") is None

    def test_invalid_format(self):
        assert _parse_bounds("not-bounds") is None


class TestHierarchyExtractor:
    def test_extract_texts_basic(self):
        items = HierarchyExtractor.extract_texts(SAMPLE_HIERARCHY_XML)
        texts = [i["text"] for i in items]
        assert "Xin chào" in texts
        assert "Đăng nhập" in texts
        assert "12345" in texts

    def test_exclude_empty(self):
        items = HierarchyExtractor.extract_texts(
            SAMPLE_HIERARCHY_XML, exclude_empty=True
        )
        for item in items:
            assert item["text"]  # no empty text

    def test_include_empty(self):
        items = HierarchyExtractor.extract_texts(
            SAMPLE_HIERARCHY_XML,
            exclude_empty=False,
            include_content_desc=False,
        )
        # ImageView has empty text AND no content_desc inclusion
        assert any(i["text"] == "" for i in items)

    def test_filter_class(self):
        items = HierarchyExtractor.extract_texts(
            SAMPLE_HIERARCHY_XML,
            filter_class=["android.widget.TextView"],
        )
        for item in items:
            assert item["class"] == "android.widget.TextView"
        assert len(items) == 2  # "Xin chào" and "12345"

    def test_content_desc_as_fallback(self):
        items = HierarchyExtractor.extract_texts(
            SAMPLE_HIERARCHY_XML,
            include_content_desc=True,
        )
        # EditText has empty text but content-desc="Email input"
        email_items = [i for i in items if i.get("text") == "Email input"]
        assert len(email_items) == 1

    def test_bounds_parsed(self):
        items = HierarchyExtractor.extract_texts(SAMPLE_HIERARCHY_XML)
        title = [i for i in items if i["text"] == "Xin chào"][0]
        assert title["bounds"] == [50, 100, 500, 150]

    def test_resource_id_included(self):
        items = HierarchyExtractor.extract_texts(SAMPLE_HIERARCHY_XML)
        title = [i for i in items if i["text"] == "Xin chào"][0]
        assert title["resource_id"] == "com.app:id/title"

    def test_plain_text(self):
        text = HierarchyExtractor.extract_plain_text(SAMPLE_HIERARCHY_XML)
        assert "Xin chào" in text
        assert "Đăng nhập" in text

    def test_empty_xml(self):
        assert HierarchyExtractor.extract_texts("") == []
        assert HierarchyExtractor.extract_texts(None) == []

    def test_invalid_xml(self):
        assert HierarchyExtractor.extract_texts("<not valid xml") == []


# ── OCREngine ─────────────────────────────────────────────────────────────────


class TestOCREnginePreprocess:
    def test_preprocess_returns_grayscale(self):
        img = Image.new("RGB", (100, 50), (200, 200, 200))
        result = OCREngine._preprocess(img, scale_factor=1.0)
        assert result.mode == "L"  # grayscale

    def test_preprocess_upscales(self):
        img = Image.new("RGB", (100, 50), (200, 200, 200))
        result = OCREngine._preprocess(img, scale_factor=2.0)
        assert result.width == 200
        assert result.height == 100

    def test_preprocess_binarizes(self):
        img = Image.new("RGB", (100, 50), (200, 200, 200))
        result = OCREngine._preprocess(img, scale_factor=1.0)
        arr = np.array(result)
        # Should only contain 0 and 255 (binary)
        unique = set(np.unique(arr))
        assert unique.issubset({0, 255})


class TestOCREngineCrop:
    def test_crop_full_region(self):
        img = Image.new("RGB", (1000, 2000))
        result = OCREngine._crop_region(img, {"x1": 0, "y1": 0, "x2": 1.0, "y2": 1.0})
        assert result.size == (1000, 2000)

    def test_crop_center(self):
        img = Image.new("RGB", (1000, 2000))
        result = OCREngine._crop_region(img, {"x1": 0.25, "y1": 0.25, "x2": 0.75, "y2": 0.75})
        assert result.size == (500, 1000)

    def test_crop_partial(self):
        img = Image.new("RGB", (100, 200))
        result = OCREngine._crop_region(img, {"x1": 0.1, "y1": 0.2, "x2": 0.9, "y2": 0.8})
        assert result.width == 80
        assert result.height == 120


class TestOCREngineExtract:
    @pytest.fixture
    def ocr(self):
        engine = OCREngine()
        if not engine.available:
            pytest.skip("Tesseract not installed")
        return engine

    def test_extract_text_basic(self, ocr):
        img_bytes = _make_text_image("Hello World")
        text = ocr.extract_text(img_bytes)
        # Tesseract should find at least part of the text
        assert len(text) > 0

    def test_extract_text_with_region(self, ocr):
        img_bytes = _make_text_image("Test Region", width=400, height=200)
        text = ocr.extract_text(
            img_bytes,
            region={"x1": 0, "y1": 0, "x2": 1.0, "y2": 1.0},
        )
        assert isinstance(text, str)

    def test_extract_with_boxes(self, ocr):
        img_bytes = _make_text_image("Box Test")
        boxes = ocr.extract_with_boxes(img_bytes)
        assert isinstance(boxes, list)
        for box in boxes:
            assert "text" in box
            assert "left" in box
            assert "top" in box
            assert "conf" in box

    def test_extract_with_boxes_actually_finds_text(self, ocr):
        """Regression: the TSV path silently returned [] for every image.

        `_run_tesseract_tsv` passed "--psm 11" and "--oem 3" as single argv
        entries, so tesseract exited 1 and the empty list looked like "no text
        on screen". Asserting the list *type* (as the test above does) cannot
        catch that — only asserting content can.
        """
        boxes = ocr.extract_with_boxes(_make_text_image("Hello World"))
        assert boxes, "OCR returned no boxes for an image that clearly has text"
        found = " ".join(b["text"] for b in boxes).lower()
        assert "hello" in found or "world" in found

    def test_region_is_applied_exactly_once(self, ocr):
        """Regression: callers cropped, then handed the same region to the engine.

        The engine crops relative to whatever it receives, so applying a
        30%-60% band twice yields a band of a band — wrong height and wrong
        offset. Text placed in the lower half must be readable when the region
        selects the lower half.
        """
        from PIL import ImageDraw, ImageFont

        img = Image.new("RGB", (400, 400), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        except (OSError, IOError):
            font = ImageFont.load_default()
        draw.text((20, 260), "Bottom", fill=(0, 0, 0), font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        boxes = ocr.extract_with_boxes(
            buf.getvalue(), region={"x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 1.0}
        )
        found = " ".join(b["text"] for b in boxes).lower()
        assert "bottom" in found

    def test_available_property(self):
        engine = OCREngine()
        assert isinstance(engine.available, bool)

    def test_unavailable_engine(self):
        # Force tesseract backend with bad cmd so it can't find binary; paddle also
        # not installed in test env → should raise.
        engine = OCREngine(tesseract_cmd="/nonexistent/path", backend="tesseract")
        assert engine.available is False
        with pytest.raises(RuntimeError, match="No OCR backend available"):
            engine.extract_text(b"fake")


# ── AIVisionExtractor Helpers ─────────────────────────────────────────────────


class TestStripMarkdownJson:
    def test_clean_json(self):
        assert _strip_markdown_json('{"key": "value"}') == '{"key": "value"}'

    def test_json_code_block(self):
        result = _strip_markdown_json('```json\n{"key": "value"}\n```')
        assert result == '{"key": "value"}'

    def test_plain_code_block(self):
        result = _strip_markdown_json('```\n{"a": 1}\n```')
        assert result == '{"a": 1}'

    def test_no_fences(self):
        assert _strip_markdown_json("plain text") == "plain text"


class TestAIVisionCropRegion:
    def test_crop_produces_valid_jpeg(self):
        img_bytes = _make_test_image(400, 800)
        cropped = AIVisionExtractor._crop_region(
            img_bytes, {"x1": 0.1, "y1": 0.2, "x2": 0.9, "y2": 0.8}
        )
        # Should be valid JPEG
        img = Image.open(io.BytesIO(cropped))
        assert img.format == "JPEG"
        # Should be smaller than original
        assert img.width < 400
        assert img.height < 800


class TestAIVisionExtractErrors:
    def test_unknown_provider_raises(self):
        ai = AIVisionExtractor()
        with pytest.raises(ValueError, match="Unknown provider"):
            ai.extract(b"fake", "test prompt", provider="invalid")

    def test_missing_openai_key(self):
        ai = AIVisionExtractor()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                ai._extract_openai(b"fake", "test", "text", None)

    def test_missing_gemini_key(self):
        ai = AIVisionExtractor()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                ai._extract_gemini(b"fake", "test", "text", None)


# ── Scenario Step Integration ─────────────────────────────────────────────────


class TestScenarioStepTypes:
    def test_step_types_registered(self):
        from common.scenario_schema import SCENARIO_STEP_TYPES, STEP_SCHEMA
        for st in ["extract_text_hierarchy", "extract_text_ocr", "extract_text_ai", "extract_screen_data"]:
            assert st in SCENARIO_STEP_TYPES
            assert st in STEP_SCHEMA
            assert "required" in STEP_SCHEMA[st]
            assert "save_as" in STEP_SCHEMA[st]["required"]

    def test_extract_text_hierarchy_step(self):
        """Test hierarchy extraction step in scenario executor."""
        from unittest.mock import MagicMock
        from tasks.scenario_task import run_scenario_task

        device = MagicMock()
        device.serial = "test"
        device.screen_width = 1080
        device.screen_height = 1920
        device.model = "Test"
        device.hierarchy_xml.return_value = SAMPLE_HIERARCHY_XML

        result = run_scenario_task(
            device,
            {"steps": [
                {"type": "extract_text_hierarchy", "save_as": "TEXTS", "format": "text"},
            ]},
        )
        assert result["success"] is True
        assert result["steps_executed"] == 1

    def test_extract_text_hierarchy_json_format(self):
        from unittest.mock import MagicMock
        from tasks.scenario_task import run_scenario_task
        from common.variable_resolver import VariableContext

        device = MagicMock()
        device.serial = "test"
        device.screen_width = 1080
        device.screen_height = 1920
        device.model = "Test"
        device.hierarchy_xml.return_value = SAMPLE_HIERARCHY_XML

        var_ctx = VariableContext(device_serial="test")
        result = run_scenario_task(
            device,
            {"steps": [
                {"type": "extract_text_hierarchy", "save_as": "ITEMS", "format": "json"},
            ]},
            _var_ctx=var_ctx,
        )
        assert result["success"] is True
        items = var_ctx._runtime_vars.get("ITEMS")
        assert isinstance(items, list)
        assert len(items) > 0
        assert any(i["text"] == "Xin chào" for i in items)

    def test_extract_screen_data_hierarchy_strategy(self):
        from unittest.mock import MagicMock
        from tasks.scenario_task import run_scenario_task

        device = MagicMock()
        device.serial = "test"
        device.screen_width = 1080
        device.screen_height = 1920
        device.model = "Test"
        device.hierarchy_xml.return_value = SAMPLE_HIERARCHY_XML

        result = run_scenario_task(
            device,
            {"steps": [
                {"type": "extract_screen_data", "save_as": "DATA", "strategy": "hierarchy"},
            ]},
        )
        assert result["success"] is True
        assert result["step_results"][0].get("source") == "hierarchy"

    def test_extract_missing_save_as(self):
        from unittest.mock import MagicMock
        from tasks.scenario_task import run_scenario_task

        device = MagicMock()
        device.serial = "test"
        device.screen_width = 1080
        device.screen_height = 1920
        device.model = "Test"

        result = run_scenario_task(
            device,
            {"steps": [{"type": "extract_text_ocr"}]},  # missing save_as
        )
        assert result["step_results"][0]["ok"] is False
        assert "save_as" in result["step_results"][0]["message"]
