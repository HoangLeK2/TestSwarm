"""Tests for DF-T-04-014 pre/post/fail step capture."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.campaign.dlq_service import _artifact_refs_from_steps
from services.execution.capture_service import (
    StepCaptureConfig,
    compress_jpeg,
    epic04_capture_default_enabled,
    error_only_capture_mode,
    extract_only_capture_mode,
    flush_pending_captures,
    is_captured_step,
    resolve_capture_throttle,
)
from services.execution.dsl_runtime import materialize_legacy_step
from services.execution.step_runner import execute_step_with_retry


def _make_sc(**overrides):
    sc = MagicMock()
    sc.serial = "SN1"
    sc.capture_dir = "/tmp/captures/test"
    sc.capture_enabled = True
    sc.capture_skip_settle = frozenset()
    sc.capture_settle_ms = 0
    sc.capture_stale_wait_s = 0
    sc.w = 1080
    sc.h = 1920
    sc.execution_id = "exec-1"
    sc.scenario = {"execution_id": "exec-1"}
    sc.device = MagicMock()
    sc.device.take_screenshot.return_value = b"\xff\xd8\xff\xe0" + b"x" * 400
    sc.device.hierarchy_xml.return_value = "<hierarchy/>"
    sc.device.model = "Pixel"
    sc.trace_id = "t1"
    for k, v in overrides.items():
        setattr(sc, k, v)
    return sc


def test_epic04_capture_default_on_with_execution_id():
    assert epic04_capture_default_enabled({"execution_id": "e1"}) is True
    assert epic04_capture_default_enabled({"steps": []}) is False


def test_step_capture_config_defaults():
    cfg = StepCaptureConfig.from_step({"type": "wait"})
    assert cfg.pre_capture is False
    assert cfg.post_capture is False
    assert cfg.require_capture is False


def test_extract_step_capture_defaults_on():
    cfg = StepCaptureConfig.from_step({"type": "extract"})
    assert cfg.pre_capture is True
    assert cfg.post_capture is True
    assert cfg.require_capture is False


def test_llm_extract_step_capture_defaults_on():
    cfg = StepCaptureConfig.from_step({"type": "llm_extract"})
    assert cfg.pre_capture is True
    assert cfg.post_capture is True


def test_non_extract_can_opt_into_capture():
    cfg = StepCaptureConfig.from_step(
        {"type": "wait", "pre_capture": True, "post_capture": True}
    )
    assert cfg.pre_capture is True
    assert cfg.post_capture is True


def test_materialize_legacy_passes_capture_flags():
    step = {
        "id": "s1",
        "type": "input_wait.wait",
        "pre_capture": False,
        "post_capture": True,
        "require_capture": True,
        "config": {"seconds": 1},
    }
    legacy = materialize_legacy_step(step)
    assert legacy["pre_capture"] is False
    assert legacy["require_capture"] is True


def test_capture_throttle_skips_steps():
    sc = _make_sc()
    sc.scenario = {"capture_throttle": 3}
    assert is_captured_step(sc, 0) is True
    assert is_captured_step(sc, 1) is False
    assert is_captured_step(sc, 3) is True
    assert resolve_capture_throttle({"capture_throttle": 3}) == 3


def test_extract_only_mode_skips_legacy_non_extract_capture_flags():
    sc = _make_sc()
    sc.scenario = {"execution_id": "exec-1", "capture_mode": "extract_only"}
    step = {
        "type": "wait",
        "pre_capture": True,
        "post_capture": True,
        "id": "legacy-wait",
    }
    step_result: dict = {"index": 0, "type": "wait", "ok": True}

    with patch("services.execution.capture_service._capture_payload") as cap:
        from services.execution.capture_service import capture_before_step, capture_after_step

        capture_before_step(sc, step, 0, step_result)
        capture_after_step(sc, step, 0, step_result, 0.0, sync=True)

    assert extract_only_capture_mode(sc.scenario) is True
    cap.assert_not_called()
    assert "screenshot_pre" not in step_result
    assert "screenshot" not in step_result


def test_extract_only_mode_still_honors_require_capture():
    sc = _make_sc()
    sc.scenario = {"execution_id": "exec-1", "capture_mode": "extract_only"}
    step = {"type": "wait", "require_capture": True, "id": "debug-wait"}
    step_result: dict = {"index": 0, "type": "wait", "ok": True}

    with patch(
        "services.execution.capture_service._capture_payload",
        return_value={"full": "http://minio/pre.jpg"},
    ) as cap:
        from services.execution.capture_service import capture_before_step

        capture_before_step(sc, step, 0, step_result)

    cap.assert_called_once()
    assert step_result.get("screenshot_pre")


def test_error_only_mode_skips_success_pre_post_even_for_extract():
    sc = _make_sc()
    sc.scenario = {"execution_id": "exec-1", "capture_mode": "error_only"}
    step = {"type": "extract", "strategy": "fb_posts", "id": "x1"}
    step_result: dict = {"index": 0, "type": "extract", "ok": True}

    with patch("services.execution.capture_service._capture_payload") as cap:
        from services.execution.capture_service import capture_before_step, capture_after_step

        capture_before_step(sc, step, 0, step_result)
        capture_after_step(sc, step, 0, step_result, 0.0, sync=True)

    assert error_only_capture_mode(sc.scenario) is True
    cap.assert_not_called()
    assert "screenshot_pre" not in step_result
    assert "screenshot" not in step_result


def test_error_only_mode_still_captures_failed_step():
    sc = _make_sc()
    sc.scenario = {"execution_id": "exec-1", "capture_mode": "error_only"}
    step = {"type": "wait", "id": "failed-wait"}
    step_result: dict = {"index": 0, "type": "wait", "ok": False}

    with patch(
        "services.execution.capture_service._capture_payload",
        return_value={"full": "http://minio/fail.jpg"},
    ) as cap:
        from services.execution.capture_service import capture_on_fail

        capture_on_fail(sc, step, 0, step_result)

    cap.assert_called_once()
    assert step_result.get("screenshot")


def test_compress_jpeg_reduces_large_payload():
    pytest.importorskip("PIL")
    from PIL import Image
    import random

    w, h = 800, 1600
    noise = bytes(random.randint(0, 255) for _ in range(w * h * 3))
    img = Image.frombytes("RGB", (w, h), noise)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    raw = buf.getvalue()
    out = compress_jpeg(raw, max_kb=50)
    assert len(out) <= 50 * 1024
    assert len(out) < len(raw)


def test_extract_pre_and_post_capture_default():
    sc = _make_sc()
    step = {"type": "extract", "strategy": "fb_posts", "id": "x1"}
    step_result: dict = {"index": 0, "type": "extract", "ok": True}

    with patch(
        "services.execution.capture_service._capture_payload",
        side_effect=[
            {"full": "http://minio/pre.jpg", "hierarchy": "http://minio/pre.xml"},
            {"full": "http://minio/post.jpg", "hierarchy": "http://minio/post.xml"},
        ],
    ):
        from services.execution.capture_service import capture_before_step, capture_after_step

        capture_before_step(sc, step, 0, step_result)
        capture_after_step(sc, step, 0, step_result, 0.0, sync=True)

    assert step_result.get("screenshot_pre")
    assert step_result.get("screenshot")
    arts = step_result.get("artifacts") or []
    types = {a.get("type") for a in arts}
    assert types == {"pre", "post"}


def test_non_extract_capture_default_skips_pre_and_post():
    sc = _make_sc()
    step = {"type": "wait", "seconds": 0, "id": "w1"}
    step_result: dict = {"index": 0, "type": "wait", "ok": True}

    with patch("services.execution.capture_service._capture_payload") as cap:
        from services.execution.capture_service import capture_before_step, capture_after_step

        capture_before_step(sc, step, 0, step_result)
        capture_after_step(sc, step, 0, step_result, 0.0, sync=True)

    cap.assert_not_called()
    assert "screenshot_pre" not in step_result
    assert "screenshot" not in step_result


def test_pre_capture_disabled_only_post():
    sc = _make_sc()
    step = {"type": "extract", "pre_capture": False, "id": "x1"}
    step_result: dict = {"index": 0, "type": "extract", "ok": True}

    with patch(
        "services.execution.capture_service._capture_payload",
        return_value={"full": "http://minio/post.jpg"},
    ) as cap:
        from services.execution.capture_service import capture_before_step, capture_after_step

        capture_before_step(sc, step, 0, step_result)
        capture_after_step(sc, step, 0, step_result, 0.0, sync=True)

    cap.assert_called_once()
    assert "screenshot_pre" not in step_result
    assert step_result.get("screenshot")


def test_fail_capture_wired_to_dlq_refs():
    step_results = [
        {
            "ok": False,
            "step_id": "tap1",
            "artifacts": [
                {
                    "type": "fail",
                    "screenshot_url": "http://minio/fail.jpg",
                    "hierarchy_url": "http://minio/fail.xml",
                }
            ],
            "screenshot": {"full": "http://minio/fail.jpg"},
        }
    ]
    refs = _artifact_refs_from_steps(step_results)
    assert refs["screenshot_fail"] == "http://minio/fail.jpg"
    assert refs["hierarchy_url"] == "http://minio/fail.xml"


def test_fail_capture_dlq_refs_from_temporal_details():
    step_results = [
        {
            "index": 1,
            "type": "tap",
            "ok": False,
            "message": "not found",
            "details": {
                "artifacts_json": [
                    {
                        "type": "fail",
                        "screenshot_url": "http://minio/fail.jpg",
                        "hierarchy_url": "http://minio/fail.xml",
                    }
                ],
            },
        }
    ]
    refs = _artifact_refs_from_steps(step_results)
    assert refs["screenshot_fail"] == "http://minio/fail.jpg"
    assert refs["hierarchy_url"] == "http://minio/fail.xml"


def test_dlq_refs_include_nested_run_scenario_failure_artifacts():
    step_results = [
        {
            "index": 0,
            "type": "run_scenario",
            "ok": False,
            "message": "run_scenario: sub-scenario failed",
            "sub_results": [
                {
                    "index": 4,
                    "type": "if_variable",
                    "ok": False,
                    "message": "if_variable: then branch failed",
                    "artifacts": [
                        {
                            "type": "fail",
                            "screenshot_url": "http://minio/nested-fail.jpg",
                            "screenshot_object_key": "captures/nested-fail.png",
                            "hierarchy_url": "http://minio/nested-fail.xml",
                            "hierarchy_object_key": "captures/nested-fail.xml",
                        }
                    ],
                }
            ],
        }
    ]

    refs = _artifact_refs_from_steps(step_results)

    assert refs["screenshot_fail"] == "http://minio/nested-fail.jpg"
    assert refs["screenshot_fail_object_key"] == "captures/nested-fail.png"
    assert refs["hierarchy_url"] == "http://minio/nested-fail.xml"
    assert refs["hierarchy_url_object_key"] == "captures/nested-fail.xml"


def test_require_capture_failure_fails_step():
    sc = _make_sc()
    step = {"type": "wait", "require_capture": True, "id": "w1"}
    step_result: dict = {"index": 0, "type": "wait", "ok": True}

    with patch("services.execution.capture_service._capture_payload", return_value={}):
        from services.execution.capture_service import capture_before_step

        capture_before_step(sc, step, 0, step_result)

    assert step_result["ok"] is False
    assert step_result["reason_code"] == "capture_required_failed"


def test_step_runner_fail_capture_on_failed_step():
    sc = _make_sc()
    step = {"type": "wait", "seconds": 0}

    with patch("services.execution.step_runner.dispatch_step", return_value={"ok": False, "message": "boom"}), patch(
        "services.execution.step_runner.capture_pre_step"
    ), patch("services.execution.step_runner.capture_post_step"), patch(
        "services.execution.step_runner.capture_fail_step"
    ) as fail_cap:
        result, _ = execute_step_with_retry(sc, step, 0)

    assert result["ok"] is False
    fail_cap.assert_called_once()


def test_flush_pending_captures_waits_for_async_post():
    sc = _make_sc()
    step = {"type": "extract", "id": "x1"}
    step_result: dict = {"index": 0, "type": "extract", "ok": True}

    def fake_post(_sc, _step, _idx, result, _start, _attempt):
        result["screenshot"] = {"full": "http://minio/post.jpg"}
        return {"full": "http://minio/post.jpg"}

    with patch("services.execution.capture_service._run_post_capture", side_effect=fake_post):
        from services.execution.capture_service import capture_after_step

        capture_after_step(sc, step, 0, step_result, 0.0, sync=False)
        flush_pending_captures(timeout_s=5.0)

    assert step_result.get("screenshot")


def test_capture_payload_delegates_to_epic06_capture():
    sc = _make_sc()
    fake_payload = {
        "full": "http://minio/step.png",
        "hierarchy": "http://minio/step.xml",
        "content_hash": "abc123",
        "screenshot_artifact_id": "art-1",
        "hierarchy_artifact_id": "art-2",
    }

    with patch(
        "services.execution.epic06_capture_adapter.build_step_capture_payload",
        return_value=fake_payload,
    ) as build:
        from services.execution.capture_service import _capture_payload

        out = _capture_payload(sc, {"type": "wait"}, 0, "wait_pre")

    build.assert_called_once()
    assert out["full"] == fake_payload["full"]
    assert out["screenshot_artifact_id"] == "art-1"


def test_capture_payload_carries_the_object_key_not_just_a_signed_url():
    """The stored URL expires; the object key is what survives.

    Captures used to persist the presigned URL they were handed at capture time,
    so reopening an execution an hour later rendered broken images.
    """
    from services.execution import epic06_capture_adapter

    sc = _make_sc()

    class FakeCaptureService:
        def capture_screenshot(self, _device, *, persist, execution_ctx):
            return SimpleNamespace(
                image_bytes=b"\x89PNG\r\n\x1a\n",
                object_key="org/exec-1/step-0/screenshot_fail.png",
                sha256="abc123",
                artifact_id=None,
            )

    with patch.object(
        epic06_capture_adapter, "_get_capture_service", lambda: FakeCaptureService()
    ), patch.object(
        epic06_capture_adapter, "_store_bytes", lambda *a, **k: "http://r2/expires-soon"
    ):
        payload = epic06_capture_adapter.build_step_capture_payload(sc, 0, "tap_fail")

    assert payload["screenshot_object_key"] == "org/exec-1/step-0/screenshot_fail.png"


def test_artifact_url_is_signed_at_read_time_from_the_object_key():
    from api.routes.executions import _extract_step_artifacts

    steps = [
        {
            "index": 3,
            "type": "tap",
            "ok": False,
            "artifacts_json": [
                {
                    "type": "fail",
                    "step_index": 3,
                    "screenshot_url": "http://r2/signed-an-hour-ago?X-Amz-Expires=3600",
                    "screenshot_object_key": "org/exec-1/step-3/shot.png",
                }
            ],
        }
    ]

    with patch(
        "services.content.artifact_service.presigned_artifact_url",
        return_value={"url": "http://r2/freshly-signed", "expires_at": "", "content_type": ""},
    ):
        arts = _extract_step_artifacts("exec-1", "SN1", steps, None)

    assert [a.url for a in arts] == ["http://r2/freshly-signed"]


def test_artifact_url_falls_back_to_the_stored_url_for_legacy_rows():
    """Rows written before the object key existed must still resolve."""
    from api.routes.executions import _extract_step_artifacts

    steps = [
        {
            "index": 1,
            "type": "tap",
            "ok": False,
            "artifacts_json": [
                {"type": "fail", "step_index": 1, "screenshot_url": "/captures/old.png"}
            ],
        }
    ]

    arts = _extract_step_artifacts("exec-1", "SN1", steps, None)

    assert [a.url for a in arts] == ["/captures/old.png"]


def test_artifact_proxy_still_wins_over_a_signed_object_url():
    """The artifact proxy is tenant-checked; prefer it whenever it exists."""
    from api.routes.executions import _extract_step_artifacts

    steps = [
        {
            "index": 2,
            "type": "tap",
            "ok": False,
            "artifacts_json": [
                {
                    "type": "fail",
                    "step_index": 2,
                    "screenshot_url": "http://r2/stale",
                    "screenshot_object_key": "org/exec-1/step-2/shot.png",
                    "screenshot_artifact_id": "11111111-1111-1111-1111-111111111111",
                }
            ],
        }
    ]

    arts = _extract_step_artifacts("exec-1", "SN1", steps, None)

    assert [a.url for a in arts] == [
        "/artifacts/11111111-1111-1111-1111-111111111111/content"
    ]


def test_fail_capture_uses_the_real_step_index_not_the_mini_scenario_zero():
    """Temporal wraps each step in a 1-step scenario, so the local index is 0.

    Without the offset every capture in a run shared one screenshot cache key,
    one ``step-0/`` object prefix, and one step number in the UI.
    """
    from services.execution import epic06_capture_adapter

    sc = _make_sc()
    sc.scenario = {"execution_id": "exec-1", "_step_index_offset": 7}
    seen: list[int] = []

    class FakeCaptureService:
        def capture_screenshot(self, _device, *, persist, execution_ctx):
            seen.append(execution_ctx.step_index)
            return SimpleNamespace(
                image_bytes=b"\x89PNG\r\n\x1a\n",
                object_key="k",
                sha256="h",
                artifact_id=None,
            )

    with patch.object(
        epic06_capture_adapter, "_get_capture_service", lambda: FakeCaptureService()
    ), patch.object(epic06_capture_adapter, "_store_bytes", lambda *a, **k: "http://r2/x"):
        payload = epic06_capture_adapter.build_step_capture_payload(sc, 0, "tap_fail")

    assert seen == [7]
    assert payload["step_index"] == 7


def test_failure_screenshot_is_never_served_from_the_cache():
    """A fail frame must be the screen at the moment of failure.

    The 30s cache is right for pre/post and wrong here: on the Temporal path two
    steps failing within the window used to get the same picture.
    """
    from services.content.extraction import capture_service as extraction_capture
    from services.content.extraction.models import ExecutionCaptureContext

    extraction_capture.clear_capture_cache()
    device = MagicMock()
    device.serial = "SN1"
    device.take_screenshot.side_effect = [b"\x89PNG\r\n\x1a\n" + b"a", b"\x89PNG\r\n\x1a\n" + b"b"]
    svc = extraction_capture.ExtractionCaptureService()
    ctx = ExecutionCaptureContext(
        execution_id="exec-1", step_index=0, kind="screenshot_fail", org_id="org-1"
    )

    first = svc.capture_screenshot(device, persist=False, execution_ctx=ctx)
    second = svc.capture_screenshot(device, persist=False, execution_ctx=ctx)

    assert first.image_bytes != second.image_bytes
    assert device.take_screenshot.call_count == 2


def test_failure_screenshot_falls_back_to_fresh_capture_when_cache_empty():
    from services.content.extraction import capture_service as extraction_capture
    from services.content.extraction.models import ExecutionCaptureContext

    extraction_capture.clear_capture_cache()
    device = MagicMock()
    device.serial = "SN1"
    device.take_screenshot.return_value = None
    device.capture_screenshot.return_value = b"\x89PNG\r\n\x1a\n" + b"fresh"
    svc = extraction_capture.ExtractionCaptureService()
    ctx = ExecutionCaptureContext(
        execution_id="exec-1", step_index=0, kind="screenshot_fail", org_id="org-1"
    )

    shot = svc.capture_screenshot(device, persist=False, execution_ctx=ctx)

    assert shot.image_bytes
    device.capture_screenshot.assert_called_once_with(
        allow_ws_u2_fallback=True,
        skip_cache=True,
    )


def test_failure_screenshot_requests_stream_frame_before_fresh_capture():
    from services.content.extraction import capture_service as extraction_capture
    from services.content.extraction.models import ExecutionCaptureContext

    extraction_capture.clear_capture_cache()
    device = MagicMock()
    device.serial = "SN1"
    device.take_screenshot.side_effect = [None, None, b"\x89PNG\r\n\x1a\n" + b"frame"]
    svc = extraction_capture.ExtractionCaptureService()
    ctx = ExecutionCaptureContext(
        execution_id="exec-1", step_index=0, kind="screenshot_fail", org_id="org-1"
    )

    shot = svc.capture_screenshot(device, persist=False, execution_ctx=ctx)

    assert shot.image_bytes
    device.request_stream_jpeg_frames.assert_called_once_with(duration_s=2.0)
    device.capture_screenshot.assert_not_called()


def test_failure_screenshot_uses_hierarchy_diagnostic_when_transport_unavailable():
    from services.content.extraction import capture_service as extraction_capture
    from services.content.extraction.models import ExecutionCaptureContext

    extraction_capture.clear_capture_cache()
    device = MagicMock()
    device.serial = "SN1"
    device.take_screenshot.return_value = None
    device.capture_screenshot.return_value = None
    device.hierarchy_xml.return_value = (
        '<hierarchy><node text="Facebook" content-desc="Home" /></hierarchy>'
    )
    svc = extraction_capture.ExtractionCaptureService()
    ctx = ExecutionCaptureContext(
        execution_id="exec-1", step_index=0, kind="screenshot_fail", org_id="org-1"
    )

    shot = svc.capture_screenshot(device, persist=False, execution_ctx=ctx)

    assert shot.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    device.hierarchy_xml.assert_called_once_with(force_refresh=True)


def test_retry_keeps_the_evidence_of_the_attempt_that_failed():
    """A step that failed then passed used to leave no screenshot at all."""
    sc = _make_sc()
    step = {
        "type": "extract",
        "id": "x1",
        "retry": {"max_attempts": 2, "backoff_ms": 0, "jitter": 0},
    }
    outcomes = [
        # retryable=True short-circuits the reason-code check, so the retry does
        # not depend on which codes the default policy happens to allow.
        {"ok": False, "message": "boom", "reason_code": "timeout", "retryable": True},
        {"ok": True},
    ]

    def fake_post(_sc, _step, _idx, result, *_a, **_k):
        if not result.get("ok", True):
            result.setdefault("artifacts", []).append({"type": "post", "attempt": "first"})

    with patch(
        "services.execution.step_runner.dispatch_step", side_effect=outcomes
    ), patch("services.execution.step_runner.capture_pre_step"), patch(
        "services.execution.step_runner.capture_post_step", side_effect=fake_post
    ), patch("services.execution.step_runner.capture_fail_step"):
        result, attempts = execute_step_with_retry(sc, step, 0)

    assert result["ok"] is True
    assert attempts == 2
    assert [a["attempt"] for a in result.get("artifacts") or []] == ["first"]


def test_capture_failure_is_recorded_even_when_capture_is_not_required():
    """A lost screenshot and a step that never captured one looked identical."""
    sc = _make_sc()
    # extract, not wait: capture defaults on for extract steps, so this exercises
    # a real capture attempt that came back empty rather than one that never ran.
    step = {"type": "extract", "id": "x1"}
    step_result: dict = {"index": 0, "type": "extract", "ok": True}

    with patch("services.execution.capture_service._capture_payload", return_value={}):
        from services.execution.capture_service import capture_before_step

        capture_before_step(sc, step, 0, step_result)

    assert step_result["ok"] is True
    assert step_result["capture_error"] == {"pre": "empty capture"}


def test_epic06_capture_payload_skips_xml_artifact_by_default(monkeypatch):
    from services.execution import epic06_capture_adapter

    sc = _make_sc()
    calls: list[tuple[str, str | None]] = []

    class FakeCaptureService:
        def capture_screenshot(self, _device, *, persist, execution_ctx):
            calls.append(("screenshot", execution_ctx.kind if execution_ctx else None))
            return SimpleNamespace(
                image_bytes=b"\x89PNG\r\n\x1a\n",
                object_key="captures/step.png",
                sha256="abc123",
                artifact_id="art-screenshot",
            )

        def capture_hierarchy(self, _device, *, persist, execution_ctx):
            calls.append(("hierarchy", execution_ctx.kind if execution_ctx else None))
            return SimpleNamespace(
                xml_bytes=b"<hierarchy/>",
                object_key="captures/step.xml",
                artifact_id="art-hierarchy",
            )

    store_calls: list[dict] = []
    monkeypatch.setattr(epic06_capture_adapter, "_get_capture_service", lambda: FakeCaptureService())

    def fake_store(*args, **kwargs):
        store_calls.append(kwargs)
        return "http://minio/artifact"

    monkeypatch.setattr(epic06_capture_adapter, "_store_bytes", fake_store)
    monkeypatch.delenv("DEVICE_FARM_STEP_CAPTURE_XML_ARTIFACTS_ENABLED", raising=False)

    payload = epic06_capture_adapter.build_step_capture_payload(
        sc,
        0,
        "social_open_comments_pre",
    )

    assert payload["full"] == "http://minio/artifact"
    assert "hierarchy" not in payload
    assert "hierarchy_artifact_id" not in payload
    assert calls == [("screenshot", "screenshot_pre")]
    assert [c["content_type"] for c in store_calls] == ["image/png"]


def test_epic06_capture_payload_xml_artifact_opt_in_uses_db_safe_kinds(monkeypatch):
    from services.execution import epic06_capture_adapter

    sc = _make_sc()
    captured_kinds: list[tuple[str, str | None]] = []

    class FakeCaptureService:
        def capture_screenshot(self, _device, *, persist, execution_ctx):
            captured_kinds.append(("screenshot", execution_ctx.kind if execution_ctx else None))
            return SimpleNamespace(
                image_bytes=b"\x89PNG\r\n\x1a\n",
                object_key="captures/step.png",
                sha256="abc123",
                artifact_id="art-screenshot",
            )

        def capture_hierarchy(self, _device, *, persist, execution_ctx):
            captured_kinds.append(("hierarchy", execution_ctx.kind if execution_ctx else None))
            return SimpleNamespace(
                xml_bytes=b"<hierarchy/>",
                object_key="captures/step.xml",
                artifact_id="art-hierarchy",
            )

    monkeypatch.setattr(epic06_capture_adapter, "_get_capture_service", lambda: FakeCaptureService())
    monkeypatch.setattr(epic06_capture_adapter, "_store_bytes", lambda *args, **kwargs: "http://minio/artifact")
    monkeypatch.setenv("DEVICE_FARM_STEP_CAPTURE_XML_ARTIFACTS_ENABLED", "1")

    payload = epic06_capture_adapter.build_step_capture_payload(
        sc,
        0,
        "social_open_comments_pre",
    )

    assert payload["full"] == "http://minio/artifact"
    assert captured_kinds == [
        ("screenshot", "screenshot_pre"),
        ("hierarchy", "hierarchy_pre"),
    ]
    assert all(kind is None or len(kind) <= 32 for _, kind in captured_kinds)
