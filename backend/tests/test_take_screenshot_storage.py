"""take_screenshot must report where the frame went, not carry it.

It used to put base64 straight into the step result, which then rode the whole
Temporal path. A measured 499KB JPEG is ~665KB encoded, against Temporal's
256KB warn / 2MB error limits, so three such steps killed a workflow.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tasks.scenario.steps.interaction import handle_take_screenshot


def _ctx(tmp_path=None):
    return SimpleNamespace(
        serial="dev1",
        execution_id="exec-1",
        capture_dir=str(tmp_path) if tmp_path else "",
        device=SimpleNamespace(capture_screenshot=lambda: b"\xff\xd8jpegbytes"),
    )


def _run(step, *, save_capture):
    result: dict = {"ok": True}
    with patch("services.capture_store.save_capture", side_effect=save_capture):
        handle_take_screenshot(_ctx(), step, 3, result)
    return result


def test_stores_the_frame_and_reports_a_url():
    result = _run({"type": "take_screenshot"}, save_capture=lambda *a, **k: "https://cdn/x.jpg")

    assert result["ok"] is True
    assert result["screenshot"] == "https://cdn/x.jpg"
    # No base64: the whole point is that bytes never enter the payload.
    assert len(result["screenshot"]) < 200


def test_records_an_artifact_reference():
    result = _run({"type": "take_screenshot", "id": "s7"}, save_capture=lambda *a, **k: "https://cdn/x.jpg")

    refs = result["artifacts_json"]
    assert len(refs) == 1
    assert refs[0]["screenshot_url"] == "https://cdn/x.jpg"
    assert refs[0]["step_index"] == 3
    assert refs[0]["step_id"] == "s7"


def test_missing_frame_fails_the_step():
    result: dict = {"ok": True}
    ctx = _ctx()
    ctx.device = SimpleNamespace(capture_screenshot=lambda: None)
    handle_take_screenshot(ctx, {"type": "take_screenshot"}, 0, result)

    assert result["ok"] is False
    assert "no frame" in result["message"]


def test_upload_failure_fails_the_step_when_there_is_nothing_else():
    def _boom(*a, **k):
        raise RuntimeError("object upload unavailable")

    result = _run({"type": "take_screenshot"}, save_capture=_boom)

    assert result["ok"] is False
    assert "could not store frame" in result["message"]


def test_upload_failure_is_tolerated_when_save_path_was_written(tmp_path):
    """The author asked for a file; losing the upload must not fail the run."""
    def _boom(*a, **k):
        raise RuntimeError("object upload unavailable")

    target = tmp_path / "shot.jpg"
    result = _run({"type": "take_screenshot", "save_path": str(target)}, save_capture=_boom)

    assert result["ok"] is True
    assert target.read_bytes() == b"\xff\xd8jpegbytes"
    assert "not uploaded" in result["message"]


def test_tap_image_reports_a_missing_dependency_instead_of_crashing():
    """`except ImageMatchError` used to reference a name imported inside the try.

    If that import failed, evaluating the except clause raised NameError and
    escaped as a crash, hiding the real cause.
    """
    from tasks.scenario.steps.interaction import handle_tap_image

    result: dict = {"ok": True}
    step = {"type": "tap_image", "template_key": "k.png"}
    with patch.dict(
        "sys.modules",
        {"services.content.extraction.image_match_service": None},
    ):
        handle_tap_image(_ctx(), step, 0, result)

    assert result["ok"] is False
    assert "tap_image unavailable" in result["message"]
