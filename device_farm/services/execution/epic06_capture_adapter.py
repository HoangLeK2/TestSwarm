"""Epic 04 step capture via Epic 06 ExtractionCaptureService (DF-T-04-014 + DF-T-06-003)."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)

_capture_svc: Any | None = None
_ARTIFACT_KIND_MAX_LEN = 32
_STEP_CAPTURE_PHASES = {"pre", "post", "fail"}
_STEP_CAPTURE_XML_ENV = "DEVICE_FARM_STEP_CAPTURE_XML_ARTIFACTS_ENABLED"


def _step_capture_xml_enabled() -> bool:
    raw = os.environ.get(_STEP_CAPTURE_XML_ENV)
    if raw is None or str(raw).strip() == "":
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _get_capture_service() -> Any:
    global _capture_svc
    if _capture_svc is None:
        from services.content.extraction.capture_service import ExtractionCaptureService

        _capture_svc = ExtractionCaptureService()
    return _capture_svc


def capture_active(sc: "ScenarioContext") -> bool:
    """True when step capture should run (local dir and/or execution-bound MinIO)."""
    if not sc.capture_enabled:
        return False
    if sc.capture_dir:
        return True
    exec_id = sc.execution_id or sc.scenario.get("execution_id") or sc.scenario.get("run_id")
    return bool(exec_id)


def absolute_step_index(sc: "ScenarioContext", step_idx: int) -> int:
    """Map a scenario-local step index onto its position in the real run.

    The Temporal path wraps each step in its own 1-step mini-scenario, so
    ``step_idx`` is always 0 there. Everything keyed on the step index — the
    screenshot cache, the object key, the step number shown in the UI — collided
    across the whole run until the offset was carried through.
    """
    scenario = getattr(sc, "scenario", None)
    if not isinstance(scenario, dict):
        return step_idx
    offset = scenario.get("_step_index_offset")
    # Checked rather than coerced: int() on a MagicMock quietly returns 1, which
    # would shift every index in tests that stub the scenario context.
    if not isinstance(offset, int) or isinstance(offset, bool):
        return step_idx
    return step_idx + offset


def _paths(sc: "ScenarioContext", step_idx: int, tag: str) -> tuple[str, str, str]:
    prefix = f"step_{step_idx:03d}_{tag}"
    capture_dir = sc.capture_dir or ""
    session_name = os.path.basename(capture_dir) if capture_dir else "execution"
    minio_prefix = f"captures/{session_name}"
    return prefix, capture_dir, minio_prefix


def _artifact_kind(prefix: str, tag: str) -> str:
    raw_tag = str(tag or "").strip("_")
    phase = raw_tag.rsplit("_", 1)[-1] if raw_tag else ""
    kind = f"{prefix}_{phase}" if phase in _STEP_CAPTURE_PHASES else f"{prefix}_{raw_tag}".strip("_")
    if len(kind) <= _ARTIFACT_KIND_MAX_LEN:
        return kind

    digest = hashlib.sha1(kind.encode("utf-8")).hexdigest()[:8]
    head_len = _ARTIFACT_KIND_MAX_LEN - len(digest) - 1
    return f"{kind[:head_len].rstrip('_')}_{digest}"


def _object_url(object_key: str, data: bytes, content_type: str) -> str | None:
    from services import minio_store

    if not minio_store.enabled():
        return None
    url = minio_store.presigned_get(object_key)
    if url:
        return url
    return minio_store.upload(data, object_key, content_type=content_type)


def _store_bytes(
    data: bytes,
    *,
    object_key: str | None,
    local_path: str,
    minio_key: str,
    content_type: str,
) -> str | None:
    from services import capture_store, minio_store

    if object_key and minio_store.enabled():
        url = _object_url(object_key, data, content_type)
        if url:
            return url
    return capture_store.save_capture(
        data,
        local_path,
        minio_key,
        content_type,
        skip_quality=True,
    )


def build_step_capture_payload(
    sc: "ScenarioContext",
    step_idx: int,
    tag: str,
    *,
    bounds: dict[str, int] | None = None,
    selector: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Capture screenshot (+ optional XML/selector/element) for one step phase."""
    from services.content.extraction.scenario_bridge import execution_capture_ctx

    capture = _get_capture_service()
    abs_idx = absolute_step_index(sc, step_idx)
    prefix, capture_dir, minio_prefix = _paths(sc, abs_idx, tag)

    screenshot_kind = _artifact_kind("screenshot", tag)
    screenshot_ctx = execution_capture_ctx(sc, abs_idx, screenshot_kind)
    capture_xml = _step_capture_xml_enabled()
    hierarchy_ctx = (
        execution_capture_ctx(sc, abs_idx, _artifact_kind("hierarchy", tag))
        if capture_xml
        else None
    )
    persist = screenshot_ctx is not None

    screenshot_handle = capture.capture_screenshot(
        sc.device,
        persist=persist,
        execution_ctx=screenshot_ctx,
    )
    if not screenshot_handle or not screenshot_handle.image_bytes:
        return {}

    png = screenshot_handle.image_bytes
    full_local = os.path.join(capture_dir, f"{prefix}_full.png") if capture_dir else ""
    full_key = screenshot_handle.object_key or f"{minio_prefix}/{prefix}_full.png"
    full_url = _store_bytes(
        png,
        object_key=screenshot_handle.object_key,
        local_path=full_local,
        minio_key=full_key,
        content_type="image/png",
    )
    if not full_url:
        return {}

    result: dict[str, Any] = {
        "full": full_url,
        "content_hash": screenshot_handle.sha256,
        "step_index": abs_idx,
    }
    if screenshot_handle.artifact_id:
        result["screenshot_artifact_id"] = screenshot_handle.artifact_id
    # Carry the object key, not just the URL. `full_url` is a presigned GET that
    # expires while the row it gets written into does not, so an execution opened
    # an hour later rendered broken images. The read path re-signs from this.
    if screenshot_handle.object_key:
        result["screenshot_object_key"] = screenshot_handle.object_key

    if capture_xml:
        try:
            hier_handle = capture.capture_hierarchy(
                sc.device,
                persist=bool(hierarchy_ctx),
                execution_ctx=hierarchy_ctx,
            )
            if hier_handle and hier_handle.xml_bytes:
                xml_local = os.path.join(capture_dir, f"{prefix}_hierarchy.xml") if capture_dir else ""
                xml_key = hier_handle.object_key or f"{minio_prefix}/{prefix}_hierarchy.xml"
                xml_url = _store_bytes(
                    hier_handle.xml_bytes,
                    object_key=hier_handle.object_key,
                    local_path=xml_local,
                    minio_key=xml_key,
                    content_type="application/xml",
                )
                if xml_url:
                    result["hierarchy"] = xml_url
                if hier_handle.artifact_id:
                    result["hierarchy_artifact_id"] = hier_handle.artifact_id
                if hier_handle.object_key:
                    result["hierarchy_object_key"] = hier_handle.object_key
        except Exception as exc:
            log.debug("hierarchy capture skipped for %s: %s", tag, exc)

    if selector:
        sel_local = os.path.join(capture_dir, f"{prefix}_selector.json") if capture_dir else ""
        sel_key = f"{minio_prefix}/{prefix}_selector.json"
        sel_bytes = json.dumps(selector, ensure_ascii=False, indent=2).encode("utf-8")
        sel_url = _store_bytes(
            sel_bytes,
            object_key=None,
            local_path=sel_local,
            minio_key=sel_key,
            content_type="application/json",
        )
        if sel_url:
            result["selector"] = sel_url

    if bounds:
        result["bounds"] = [bounds["left"], bounds["top"], bounds["right"], bounds["bottom"]]

    return result
