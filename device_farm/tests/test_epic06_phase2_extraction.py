"""Epic 06 Phase 2 tests — capture, hierarchy, OCR, retention."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image

from services.content.extraction.capture_service import ExtractionCaptureService, clear_capture_cache
from services.content.extraction.hierarchy.parser import parse_hierarchy_root
from services.content.extraction.hierarchy.service import HierarchyService
from services.content.extraction.hierarchy.traversal import find_by_resource_id
from services.content.extraction.models import CaptureError, ExecutionCaptureContext, StrategyMismatchError
from services.content.extraction.retention import ArtifactRetentionService, RetentionPolicy, _retention_days_for


@pytest.fixture(autouse=True)
def _reset_capture_cache():
    clear_capture_cache()
    yield
    clear_capture_cache()


_SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node index="0" text="Hello" resource-id="com.app:id/title" class="android.widget.TextView" bounds="[10,10][200,50]" />
    <node index="1" text="" resource-id="com.app:id/like_btn" class="android.widget.Button" bounds="[10,60][100,90]" content-desc="Like" />
  </node>
</hierarchy>"""


class FakeDevice:
    serial = "fake-01"

    def __init__(self, *, online: bool = True) -> None:
        self._online = online

    def take_screenshot(self):
        if not self._online:
            return None
        img = Image.new("RGB", (100, 50), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def hierarchy_xml(self, force_refresh: bool = False):
        if not self._online:
            return None
        return _SAMPLE_XML


class TestCaptureService:
    def test_png_normalization_when_persisting(self, monkeypatch):
        """Stored artifacts are declared image/png, so they must really be PNG."""
        from services import minio_store

        monkeypatch.setattr(minio_store, "enabled", lambda: False)
        monkeypatch.setattr(minio_store, "local_image_fallback_enabled", lambda: True)
        device = FakeDevice()
        svc = ExtractionCaptureService()
        ctx = ExecutionCaptureContext(execution_id="e-png", step_index=0, kind="screenshot_ocr")
        handle = svc.capture_screenshot(device, persist=True, execution_ctx=ctx)
        assert handle.image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert handle.size_bytes > 0

    def test_png_normalization_even_when_not_persisting(self):
        """Callers write these bytes out as .png regardless of `persist`.

        epic06_capture_adapter stores handle.image_bytes to `<prefix>_full.png`
        with content_type image/png on both branches, so returning the device's
        raw JPEG here would put a JPEG inside a file claiming to be a PNG.
        """
        device = FakeDevice()
        svc = ExtractionCaptureService()
        handle = svc.capture_screenshot(device, persist=False)
        assert handle.image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert handle.size_bytes > 0

    def test_capture_cache_hit(self):
        device = FakeDevice()
        svc = ExtractionCaptureService()
        ctx = ExecutionCaptureContext(execution_id="e1", step_index=1, kind="screenshot_pre")
        h1 = svc.capture_screenshot(device, persist=False, execution_ctx=ctx)
        h2 = svc.capture_screenshot(device, persist=False, execution_ctx=ctx)
        assert h1.sha256 == h2.sha256

    def test_device_offline_raises(self):
        svc = ExtractionCaptureService()
        with pytest.raises(CaptureError) as exc:
            svc.capture_screenshot(FakeDevice(online=False), persist=False)
        assert exc.value.code == "DEVICE_OFFLINE"

    def test_persist_without_context_raises(self):
        svc = ExtractionCaptureService()
        with pytest.raises(CaptureError) as exc:
            svc.capture_screenshot(FakeDevice(), persist=True, execution_ctx=None)
        assert exc.value.code == "MISSING_CONTEXT"

    def test_persist_requires_object_storage_upload(self, monkeypatch):
        from services import minio_store

        monkeypatch.setattr(minio_store, "enabled", lambda: False)
        monkeypatch.setattr(minio_store, "local_image_fallback_enabled", lambda: False)
        svc = ExtractionCaptureService()
        ctx = ExecutionCaptureContext(execution_id="e1", step_index=1, kind="screenshot_pre")
        with pytest.raises(CaptureError) as exc:
            svc.capture_screenshot(FakeDevice(), persist=True, execution_ctx=ctx)
        assert exc.value.code == "OBJECT_STORAGE_UNAVAILABLE"

    def test_hierarchy_persist_tolerates_object_storage_unavailable(self, monkeypatch):
        from services import minio_store

        monkeypatch.setattr(minio_store, "enabled", lambda: False)
        svc = ExtractionCaptureService()
        ctx = ExecutionCaptureContext(execution_id="e1", step_index=1, kind="hierarchy")

        handle = svc.capture_hierarchy(FakeDevice(), persist=True, execution_ctx=ctx)

        assert handle.xml_bytes.startswith(b"<?xml")
        assert handle.object_key is None
        assert handle.artifact_id is None


class TestHierarchyService:
    def test_screen_data_strategy(self):
        svc = HierarchyService()
        result = svc.extract_from_xml(_SAMPLE_XML, "screen_data")
        assert isinstance(result.data, list)
        assert any(item.get("text") == "Hello" for item in result.data)
        assert result.latency_ms >= 0

    def test_find_by_resource_id(self):
        root = parse_hierarchy_root(_SAMPLE_XML)
        nodes = find_by_resource_id(root, "com.app:id/like_btn")
        assert len(nodes) == 1

    def test_strategy_mismatch_empty_screen(self):
        empty_xml = """<?xml version='1.0'?><hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][10,10]" /></hierarchy>"""
        svc = HierarchyService()
        with pytest.raises(StrategyMismatchError):
            svc.extract_from_xml(empty_xml, "screen_data")


class TestRetentionPolicy:
    def test_success_execution_retention_days(self):
        policy = RetentionPolicy()
        execution = SimpleNamespace(status="completed", pinned_at=None)
        artifact = SimpleNamespace(retention_class="standard", captured_at=datetime.now(timezone.utc))
        assert _retention_days_for(execution, artifact, policy) == 30

    def test_pinned_skips_retention(self):
        policy = RetentionPolicy()
        execution = SimpleNamespace(status="completed", pinned_at=datetime.now(timezone.utc))
        artifact = SimpleNamespace(retention_class="standard", captured_at=datetime.now(timezone.utc) - timedelta(days=60))
        assert _retention_days_for(execution, artifact, policy) is None

    def test_failed_execution_longer_retention(self):
        policy = RetentionPolicy()
        execution = SimpleNamespace(status="failed", pinned_at=None)
        artifact = SimpleNamespace(retention_class="standard", captured_at=datetime.now(timezone.utc))
        assert _retention_days_for(execution, artifact, policy) == 90


class _OcrDevice:
    """Device whose OCR runs on agent-boot, as it does in production."""

    serial = "dev-ocr"

    def __init__(self, *, supported: bool = True, reply: dict | None = None) -> None:
        self._supported = supported
        self._reply = reply if reply is not None else {"ok": True, "results": [], "count": 0}
        self.calls: list[dict] = []

    def ocr_supported(self) -> bool:
        return self._supported

    def request_ocr(self, **kwargs):
        self.calls.append(kwargs)
        return self._reply


class TestOCROnDevice:
    """OCR reads the screen on the agent; the farm never sees the frame.

    Since media moved to go2rtc, DeviceClient.take_screenshot() only reads a
    scrcpy JPEG cache that nothing fills any more — the farm has no frame of its
    own, so this path is the only one that works.
    """

    async def test_returns_boxes_and_no_image_on_success(self):
        from services.content.extraction.ocr_service import OCRService

        device = _OcrDevice(reply={
            "ok": True,
            "count": 2,
            "results": [
                {"text": "Hello", "left": 10, "top": 20, "width": 50, "height": 15, "conf": 91},
                {"text": "", "left": 10, "top": 60, "width": 40, "height": 15, "conf": 88},
            ],
        })
        result, image = await OCRService(confidence_threshold=0.5).extract_on_device(device)

        assert image is None
        # Whitespace-only boxes are dropped; the agent already applied the
        # confidence threshold, so everything it returns is above the bar.
        assert [r["text"] for r in result.results] == ["Hello"]
        assert result.low_confidence_results == []
        assert result.results[0]["bbox"] == {"x": 10, "y": 20, "w": 50, "h": 15}
        assert result.results[0]["confidence"] == pytest.approx(0.91)
        assert device.calls[0]["min_confidence"] == 0.5, "threshold must reach the agent"

    async def test_unsupported_agent_fails_fast_with_actionable_code(self):
        """Must not fall through to a 30s relay timeout on every OCR step."""
        from services.content.extraction.models import OCRError
        from services.content.extraction.ocr_service import OCRService

        device = _OcrDevice(supported=False)
        with pytest.raises(OCRError) as exc:
            await OCRService().extract_on_device(device)
        assert exc.value.code == "OCR_AGENT_UNSUPPORTED"
        assert device.calls == [], "should not reach the relay at all"

    async def test_agent_error_surfaces(self):
        from services.content.extraction.models import OCRError
        from services.content.extraction.ocr_service import OCRService

        device = _OcrDevice(reply={"ok": False, "error": "screenshot_unavailable"})
        with pytest.raises(OCRError) as exc:
            await OCRService().extract_on_device(device)
        assert exc.value.code == "OCR_AGENT_ERROR"
        assert "screenshot_unavailable" in str(exc.value)

    async def test_image_returned_only_when_requested_and_empty(self):
        import base64 as _b64

        from services.content.extraction.ocr_service import OCRService

        device = _OcrDevice(reply={
            "ok": True, "results": [], "count": 0,
            "image_b64": _b64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode(),
        })
        result, image = await OCRService().extract_on_device(device, want_image_on_empty=True)
        assert result.results == []
        assert image and image.startswith(b"\x89PNG")
        assert device.calls[0]["want_image_on_empty"] is True
