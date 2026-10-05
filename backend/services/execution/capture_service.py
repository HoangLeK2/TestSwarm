"""Pre/post/fail step capture for Epic 04 executions (DF-T-04-014)."""
from __future__ import annotations

import hashlib
import io
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

from services.execution.capture_policy import default_capture_enabled_for_step
from services.execution.reason_codes import CAPTURE_REQUIRED_FAILED

log = logging.getLogger(__name__)

_MAX_JPEG_KB = 200
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="step-capture")
_pending: list[tuple[dict[str, Any], Future]] = []
_pending_lock = threading.Lock()

try:
    from web.metrics import (
        capture_failure_total,
        capture_skipped_throttle_total,
        capture_success_total,
    )
except Exception:  # pragma: no cover — metrics optional in unit tests
    from prometheus_client import Counter

    capture_success_total = Counter("capture_success_total", "Step captures succeeded", ["phase"])
    capture_failure_total = Counter("capture_failure_total", "Step captures failed", ["phase"])
    capture_skipped_throttle_total = Counter(
        "capture_skipped_throttle_total", "Steps skipped by org throttle"
    )


@dataclass
class StepCaptureConfig:
    pre_capture: bool = False
    post_capture: bool = False
    require_capture: bool = False

    @classmethod
    def from_step(cls, step: dict[str, Any]) -> StepCaptureConfig:
        def _bool(key: str, default: bool) -> bool:
            val = step.get(key)
            if val is None and isinstance(step.get("config"), dict):
                val = step["config"].get(key)
            if val is None:
                return default
            return bool(val)

        require_capture = _bool("require_capture", False)
        default_capture = default_capture_enabled_for_step(step) or require_capture
        return cls(
            pre_capture=_bool("pre_capture", default_capture),
            post_capture=_bool("post_capture", default_capture),
            require_capture=require_capture,
        )


@dataclass
class CaptureSession:
    throttle: int = 1
    hash_to_ref: dict[str, dict[str, Any]] = field(default_factory=dict)


def resolve_capture_throttle(scenario: dict[str, Any]) -> int:
    for key in ("capture_throttle",):
        raw = scenario.get(key)
        if raw is not None:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
    campaign_vars = scenario.get("_campaign_vars") or {}
    if isinstance(campaign_vars, dict):
        raw = campaign_vars.get("__CAPTURE_THROTTLE__") or campaign_vars.get("capture_throttle")
        if raw is not None:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
    return 1


def _is_nested_depth(sc: "ScenarioContext") -> bool:
    """True when the step runs inside a nested scenario (then/else, loop body).

    Tolerates non-int depth (e.g. MagicMock in unit tests) by treating it as the
    top level so capture behavior there is unchanged.
    """
    depth = getattr(sc, "depth", 0)
    return isinstance(depth, int) and depth > 0


def explicit_capture_steps(scenario: dict[str, Any]) -> bool | None:
    """Tri-state capture_steps override from scenario body or campaign vars.

    Returns True/False when explicitly set (e.g. crawl fast-path disables capture
    even though the execution is campaign-bound), or None when unset.
    """
    cs = scenario.get("capture_steps")
    if isinstance(cs, bool):
        return cs
    campaign_vars = scenario.get("_campaign_vars") or {}
    if isinstance(campaign_vars, dict):
        raw = campaign_vars.get("__CAPTURE_STEPS__")
        if raw is not None:
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    return None


def error_only_capture_mode(scenario: dict[str, Any]) -> bool:
    """True when pre/post captures are disabled and only failures capture.

    Older saved scenarios may contain pre_capture/post_capture=true on every
    step because those flags were once injected as defaults. Campaign runs use
    this mode so normal success paths never capture screens; failed steps still
    use capture_on_fail to record error evidence.
    """
    raw = scenario.get("capture_mode") or scenario.get("capture_policy")
    if raw is None:
        campaign_vars = scenario.get("_campaign_vars") or {}
        if isinstance(campaign_vars, dict):
            raw = campaign_vars.get("__CAPTURE_MODE__") or campaign_vars.get("capture_mode")
    return str(raw or "").strip().lower() in {"error_only", "fail_only", "failure_only"}


def extract_only_capture_mode(scenario: dict[str, Any]) -> bool:
    """True when legacy explicit pre/post flags should not widen capture."""
    raw = scenario.get("capture_mode") or scenario.get("capture_policy")
    if raw is None:
        campaign_vars = scenario.get("_campaign_vars") or {}
        if isinstance(campaign_vars, dict):
            raw = campaign_vars.get("__CAPTURE_MODE__") or campaign_vars.get("capture_mode")
    return str(raw or "").strip().lower() in {"extract_only", "extraction_only"}


def epic04_capture_default_enabled(scenario: dict[str, Any]) -> bool:
    explicit = explicit_capture_steps(scenario)
    if explicit is not None:
        return explicit
    if scenario.get("execution_id") or scenario.get("run_id"):
        return True
    import os

    return (
        os.environ.get("CAPTURE_STEPS", "").lower() in {"1", "true", "yes"}
        or os.environ.get("DEBUG_AUTO", "").lower() in {"1", "true", "yes"}
    )


def _pre_post_capture_allowed(sc: "ScenarioContext", step: dict[str, Any]) -> bool:
    if error_only_capture_mode(sc.scenario):
        return False
    if not extract_only_capture_mode(sc.scenario):
        return True
    cfg = StepCaptureConfig.from_step(step)
    return cfg.require_capture or default_capture_enabled_for_step(step)


def get_capture_session(sc: "ScenarioContext") -> CaptureSession:
    session = getattr(sc, "_capture_session", None)
    if not isinstance(session, CaptureSession):
        session = CaptureSession(throttle=resolve_capture_throttle(sc.scenario))
        sc._capture_session = session  # type: ignore[attr-defined]
    return session


def is_captured_step(sc: "ScenarioContext", step_idx: int) -> bool:
    session = get_capture_session(sc)
    if session.throttle <= 1:
        return True
    return step_idx % session.throttle == 0


def should_capture_step(sc: "ScenarioContext", step_idx: int) -> bool:
    if is_captured_step(sc, step_idx):
        return True
    capture_skipped_throttle_total.inc()
    return False


def compress_jpeg(data: bytes, max_kb: int = _MAX_JPEG_KB) -> bytes:
    if not data or len(data) <= max_kb * 1024:
        return data
    try:
        from PIL import Image
    except ImportError:
        return data

    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    max_bytes = max_kb * 1024
    scale = 1.0
    while scale >= 0.35:
        working = img
        if scale < 1.0:
            w, h = img.size
            working = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)

        quality = 85
        best = data
        while quality >= 25:
            buf = io.BytesIO()
            working.save(buf, format="JPEG", quality=quality, optimize=True)
            out = buf.getvalue()
            best = out
            if len(out) <= max_bytes:
                return out
            quality -= 10
        data = best
        scale *= 0.75
    return data


def _device_state_summary(device: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for attr in ("model", "serial"):
        val = getattr(device, attr, None)
        if val:
            summary[attr] = val
    try:
        app = getattr(device, "current_app", None)
        if callable(app):
            cur = app()
            if cur:
                summary["current_app"] = cur
    except Exception:
        pass
    return summary


def _artifact_ref(
    *,
    capture_type: str,
    execution_id: str | None,
    step_id: str | None,
    step_type: str | None,
    step_index: int,
    attempt_index: int,
    payload: dict[str, Any],
    content_hash: str | None = None,
    dedup_ref: str | None = None,
    device: Any,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "type": capture_type,
        "execution_id": execution_id,
        "step_id": step_id,
        "step_type": step_type,
        "step_index": step_index,
        "attempt_index": attempt_index,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "device_state_summary": _device_state_summary(device),
        "screenshot_url": payload.get("full"),
        "hierarchy_url": payload.get("hierarchy"),
        "selector_url": payload.get("selector"),
        "element_url": payload.get("element"),
        "payload": payload,
    }
    if content_hash:
        ref["content_hash"] = content_hash
    if dedup_ref:
        ref["dedup_ref"] = dedup_ref
    if payload.get("screenshot_artifact_id"):
        ref["screenshot_artifact_id"] = payload["screenshot_artifact_id"]
    if payload.get("hierarchy_artifact_id"):
        ref["hierarchy_artifact_id"] = payload["hierarchy_artifact_id"]
    # Object keys outlive the presigned URLs above; the read path re-signs them.
    if payload.get("screenshot_object_key"):
        ref["screenshot_object_key"] = payload["screenshot_object_key"]
    if payload.get("hierarchy_object_key"):
        ref["hierarchy_object_key"] = payload["hierarchy_object_key"]
    return ref


def _append_artifact(step_result: dict[str, Any], ref: dict[str, Any]) -> None:
    arts = step_result.setdefault("artifacts", [])
    if isinstance(arts, list):
        arts.append(ref)
    step_result.setdefault("artifacts_json", arts)


def _dedup_or_store(
    session: CaptureSession,
    content_hash: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    existing = session.hash_to_ref.get(content_hash)
    if existing:
        return dict(existing.get("payload") or {}), existing.get("screenshot_url")
    session.hash_to_ref[content_hash] = {
        "screenshot_url": payload.get("full"),
        "payload": payload,
    }
    return payload, None


def _capture_payload(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_idx: int,
    tag: str,
    bounds: dict[str, int] | None = None,
    selector: dict[str, str] | None = None,
) -> dict[str, Any]:
    from services.execution.epic06_capture_adapter import build_step_capture_payload

    session = get_capture_session(sc)
    payload = build_step_capture_payload(
        sc,
        step_idx,
        tag,
        bounds=bounds,
        selector=selector,
    )
    if not payload:
        return {}

    content_hash = str(payload.get("content_hash") or "")
    if not content_hash:
        content_hash = hashlib.sha256(str(payload.get("full", "")).encode()).hexdigest()

    payload, dedup_url = _dedup_or_store(session, content_hash, payload)
    if dedup_url and payload.get("full") != dedup_url:
        payload = dict(payload)
        payload["full"] = dedup_url
        payload["dedup"] = True
    return payload


def _step_selector(step: dict[str, Any]) -> dict[str, str] | None:
    t = step.get("type")
    if t not in (
        "tap",
        "tap_selector",
        "wait_element",
        "assert_element",
        "input_selector",
        "long_tap_selector",
        "scroll_to",
        "if_element",
    ):
        return None
    from services.scenario_selector import normalize_step_selector

    spec = normalize_step_selector(step)
    if spec and not spec.is_empty():
        s_by, s_val = spec.primary_by_value()
        return {"by": s_by, "value": s_val}
    return None


def _record_capture_result(
    step_result: dict[str, Any],
    *,
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_idx: int,
    attempt_index: int,
    capture_type: str,
    payload: dict[str, Any],
    jpeg_hash: str | None = None,
    dedup_ref: str | None = None,
) -> None:
    step_id = str(step.get("id") or step.get("_id") or "") or None
    step_type = str(step.get("type") or "") or None
    ref = _artifact_ref(
        capture_type=capture_type,
        execution_id=sc.execution_id,
        step_id=step_id,
        step_type=step_type,
        # The payload knows the step's real position; step_idx is scenario-local
        # and is always 0 on the Temporal path.
        step_index=payload.get("step_index", step_idx),
        attempt_index=attempt_index,
        payload=payload,
        content_hash=jpeg_hash,
        dedup_ref=dedup_ref,
        device=sc.device,
    )
    _append_artifact(step_result, ref)

    if capture_type == "pre":
        step_result["screenshot_pre"] = payload
    elif capture_type in ("post", "fail"):
        step_result["screenshot"] = payload
        step_result["screenshot_post"] = payload.get("full") or payload


def _handle_capture_failure(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_result: dict[str, Any],
    phase: str,
    exc: Exception | None = None,
) -> None:
    capture_failure_total.labels(phase=phase).inc()
    msg = str(exc) if exc else "empty capture"
    log.warning("[%s] capture %s failed: %s", sc.serial, phase, msg)
    # Recorded on the step regardless of require_capture. Without this a lost
    # screenshot and a step that never captured one look identical to whoever
    # opens the run later — the only signal was a WARNING line in worker logs.
    # Keyed by phase so a pre failure cannot mask the fail-phase one, which is
    # the capture an operator actually came looking for.
    errors = step_result.get("capture_error")
    if not isinstance(errors, dict):
        errors = {}
        step_result["capture_error"] = errors
    errors[phase] = msg
    cfg = StepCaptureConfig.from_step(step)
    if cfg.require_capture:
        step_result["ok"] = False
        step_result["reason_code"] = CAPTURE_REQUIRED_FAILED
        step_result["message"] = f"capture_required_failed ({phase}): {msg}"


def capture_before_step(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_idx: int,
    step_result: dict[str, Any],
    *,
    attempt_index: int = 1,
) -> None:
    from services.execution.epic06_capture_adapter import capture_active

    if not capture_active(sc):
        return
    cfg = StepCaptureConfig.from_step(step)
    if not cfg.pre_capture:
        return
    if not _pre_post_capture_allowed(sc, step):
        return
    # Nested branch steps (then/else, loop bodies) inherit the parent's screen
    # context — skip per-step capture unless explicitly required, to avoid
    # doubling capture overhead inside crawl loops.
    if _is_nested_depth(sc) and not cfg.require_capture:
        return
    if not should_capture_step(sc, step_idx):
        return

    t = step.get("type", "unknown")
    try:
        payload = _capture_payload(sc, step, step_idx, f"{t}_pre")
        if not payload:
            _handle_capture_failure(sc, step, step_result, "pre")
            return
        capture_success_total.labels(phase="pre").inc()
        _record_capture_result(
            step_result,
            sc=sc,
            step=step,
            step_idx=step_idx,
            attempt_index=attempt_index,
            capture_type="pre",
            payload=payload,
            jpeg_hash=payload.get("content_hash"),
        )
    except Exception as exc:
        _handle_capture_failure(sc, step, step_result, "pre", exc)


def _run_post_capture(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_idx: int,
    step_result: dict[str, Any],
    step_start_t: float,
    attempt_index: int,
) -> dict[str, Any] | None:
    from tasks.scenario.capture import StaleFrameError
    import os
    import time

    cfg = StepCaptureConfig.from_step(step)
    if not cfg.post_capture or not is_captured_step(sc, step_idx):
        return None

    t = step.get("type", "unknown")
    need_settle = t not in sc.capture_skip_settle and sc.capture_settle_ms > 0
    if need_settle:
        time.sleep(sc.capture_settle_ms / 1000.0)

    stale_after_wait = False
    if need_settle and sc.capture_stale_wait_s > 0:
        poll_deadline = time.monotonic() + sc.capture_stale_wait_s
        while time.monotonic() < poll_deadline:
            ft = float(getattr(sc.device, "_last_frame_time", 0.0) or 0.0)
            if ft > step_start_t:
                break
            time.sleep(0.05)
        else:
            ft = float(getattr(sc.device, "_last_frame_time", 0.0) or 0.0)
            if ft <= step_start_t:
                stale_after_wait = True

    if stale_after_wait and (
        os.environ.get("PLATFORM_STRICT_FRESH_FRAME", "0") == "1"
        or step.get("require_fresh_frame") is True
    ):
        raise StaleFrameError(
            f"frame stale after {int(sc.capture_stale_wait_s * 1000)}ms "
            f"on step#{step_idx + 1} ({t})"
        )

    payload = _capture_payload(
        sc,
        step,
        step_idx,
        str(t),
        step_result.pop("_bounds", None),
        selector=_step_selector(step),
    )
    if not payload:
        _handle_capture_failure(sc, step, step_result, "post")
        return None
    capture_success_total.labels(phase="post").inc()
    _record_capture_result(
        step_result,
        sc=sc,
        step=step,
        step_idx=step_idx,
        attempt_index=attempt_index,
        capture_type="post",
        payload=payload,
        jpeg_hash=payload.get("content_hash"),
    )
    return payload


def capture_after_step(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_idx: int,
    step_result: dict[str, Any],
    step_start_t: float,
    *,
    attempt_index: int = 1,
    sync: bool = False,
) -> None:
    from services.execution.epic06_capture_adapter import capture_active

    if not capture_active(sc):
        return
    cfg = StepCaptureConfig.from_step(step)
    if not cfg.post_capture:
        return
    if not _pre_post_capture_allowed(sc, step):
        return
    if _is_nested_depth(sc) and not cfg.require_capture:
        return
    if not is_captured_step(sc, step_idx):
        return

    if sync or not step_result.get("ok", True):
        try:
            _run_post_capture(sc, step, step_idx, step_result, step_start_t, attempt_index)
        except Exception as exc:
            from tasks.scenario.capture import StaleFrameError

            if isinstance(exc, StaleFrameError):
                raise
            _handle_capture_failure(sc, step, step_result, "post", exc)
        return

    fut = _executor.submit(
        _run_post_capture,
        sc,
        step,
        step_idx,
        step_result,
        step_start_t,
        attempt_index,
    )
    with _pending_lock:
        _pending.append((step_result, fut))


def capture_on_fail(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_idx: int,
    step_result: dict[str, Any],
    *,
    attempt_index: int = 1,
) -> None:
    from services.execution.epic06_capture_adapter import capture_active

    if not capture_active(sc):
        return
    t = step.get("type", "unknown")
    try:
        payload = _capture_payload(
            sc,
            step,
            step_idx,
            f"{t}_fail",
            step_result.pop("_bounds", None),
            selector=_step_selector(step),
        )
        if not payload:
            _handle_capture_failure(sc, step, step_result, "fail")
            return
        capture_success_total.labels(phase="fail").inc()
        _record_capture_result(
            step_result,
            sc=sc,
            step=step,
            step_idx=step_idx,
            attempt_index=attempt_index,
            capture_type="fail",
            payload=payload,
            jpeg_hash=payload.get("content_hash"),
        )
    except Exception as exc:
        _handle_capture_failure(sc, step, step_result, "fail", exc)


def flush_pending_captures(timeout_s: float = 30.0) -> None:
    with _pending_lock:
        batch = list(_pending)
        _pending.clear()
    for step_result, fut in batch:
        try:
            fut.result(timeout=timeout_s)
        except Exception as exc:
            log.warning("async post-capture failed: %s", exc)
            if not step_result.get("ok", True):
                continue
            step_result.setdefault("capture_warnings", []).append(str(exc))
