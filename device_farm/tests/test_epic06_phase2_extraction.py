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
    def test_png_normalization_from_jpeg(self):
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


class TestOCRHelpers:
    def test_tesseract_lang_mapping(self):
        from services.content.extraction.ocr_service import _tesseract_lang

        assert _tesseract_lang(["vi", "en"]) == "vie+eng"


class TestCapturePersist:
    def test_persist_artifact_writes_row(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from services.content.extraction.capture_service import _try_persist_artifact
        from services.content.extraction.models import ExecutionCaptureContext

        ctx = ExecutionCaptureContext(
            execution_id="exec-1",
            step_index=2,
            kind="screenshot_pre",
            org_id="org-1",
        )
        captured_at = datetime.now(timezone.utc)

        with patch("db.database.run_activity_coro") as run_coro:
            run_coro.side_effect = lambda coro: __import__("asyncio").run(coro)
            with patch("db.database.activity_session") as session_cm:
                db = AsyncMock()
                session_cm.return_value.__aenter__ = AsyncMock(return_value=db)
                session_cm.return_value.__aexit__ = AsyncMock(return_value=False)
                with patch(
                    "services.content.extraction.capture_service.persist_capture_artifact",
                    new=AsyncMock(return_value="art-99"),
                ) as persist:
                    artifact_id = _try_persist_artifact(
                        ctx,
                        db=None,
                        object_key="org-1/exec-1/step-2/screenshot_pre-ts.png",
                        mime="image/png",
                        size=123,
                        sha256="abc",
                        captured_at=captured_at,
                    )
        assert artifact_id == "art-99"
        persist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_capture_artifact_includes_org_id(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from services.content.extraction.capture_service import persist_capture_artifact
        from services.content.extraction.models import ExecutionCaptureContext

        ctx = ExecutionCaptureContext(
            execution_id="exec-1",
            step_index=3,
            kind="screenshot_post",
            org_id=None,
        )
        captured_at = datetime.now(timezone.utc)
        db = AsyncMock()
        db.get = AsyncMock(return_value=MagicMock(org_id="org-99"))
        db.scalar = AsyncMock(return_value="device-1")

        with patch(
            "db.crud.execution_artifact.create_execution_artifact",
            new=AsyncMock(return_value=MagicMock(id="art-42")),
        ) as create:
            artifact_id = await persist_capture_artifact(
                db,
                ctx,
                object_key="org-99/exec-1/step-3/screenshot_post.png",
                mime="image/png",
                size=2048,
                sha256="deadbeef",
                captured_at=captured_at,
            )

        assert artifact_id == "art-42"
        create.assert_awaited_once()
        kwargs = create.await_args.kwargs
        assert kwargs["org_id"] == "org-99"
        assert kwargs["device_id"] == "device-1"


class TestScenarioBridge:
    def test_map_ocr_languages_legacy_eng(self):
        from services.content.extraction.scenario_bridge import map_ocr_languages

        assert map_ocr_languages("eng") == ["en"]

    def test_execution_capture_ctx_from_scenario(self):
        from types import SimpleNamespace

        from services.content.extraction.scenario_bridge import execution_capture_ctx

        sc = SimpleNamespace(
            execution_id=None,
            scenario={"execution_id": "e-42", "org_id": "o-1"},
        )
        ctx = execution_capture_ctx(sc, 3, "hierarchy_snapshot")
        assert ctx is not None
        assert ctx.execution_id == "e-42"
        assert ctx.step_index == 3
        assert ctx.org_id == "o-1"
