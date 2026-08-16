"""Failure-bundle capture for FB crawl observability (Phase 0).

Writes on-disk artifacts when a parse returns empty with a non-ok reason_code,
when an extraction step exhausts its retry budget, or when a step raises. Used
by operators to replay parser logic offline and diagnose flakes without
waiting for the next live run.

File layout:
    captures/_failures/<execution_id>/<step_idx>_<ts>/
        hierarchy.xml.gz
        screen.jpg            (optional)
        step_context.json     (ctx counters, not full post list)
        parse_diagnostic.json (from parser)
        traceback.txt         (if exception)

Gated by env ``FB_CAPTURE_FAILURES=1`` (default off). Silent no-op on write
error — never break scenario execution. Per-execution cap via
``FB_FAILURE_CAP`` (default 50).
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_FAILURE_COUNTS: Dict[str, int] = {}


def _is_enabled() -> bool:
    return os.environ.get("FB_CAPTURE_FAILURES", "0") == "1"


def _failure_cap() -> int:
    try:
        return max(1, int(os.environ.get("FB_FAILURE_CAP", "50")))
    except ValueError:
        return 50


def _bundle_root() -> Path:
    root = os.environ.get("FB_FAILURE_DIR")
    if root:
        return Path(root)
    # Default to device_farm/captures/_failures relative to repo root.
    here = Path(__file__).resolve()
    # tasks/scenario/failure_bundle.py -> device_farm/
    return here.parents[2] / "captures" / "_failures"


def _safe_step_ctx_snapshot(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Extract lightweight ctx fields — counts only, not full post dicts."""
    return {
        "posts_count": len(ctx.get("posts") or []),
        "comments_count": len(ctx.get("comments") or []),
        "loop_iter": ctx.get("_loop_iter"),
        "no_new_streak": ctx.get("_no_new_posts_streak") or ctx.get("_no_new_streak"),
        "active_comment_parent_pid": ctx.get("_comment_parent_pid"),
        "first_new_post_hash": ctx.get("_first_new_post_hash"),
        "break_flag": bool(ctx.get("_break")),
    }


def capture_failure_bundle(
    device: Any,
    ctx: Dict[str, Any],
    execution_id: Optional[str],
    step_idx: int,
    reason: str,
    xml: Optional[str] = None,
    diagnostic: Optional[Dict[str, Any]] = None,
    exc: Optional[BaseException] = None,
) -> Optional[str]:
    """Write a failure bundle; return its path or None.

    Silent no-op if ``FB_CAPTURE_FAILURES`` is unset or per-execution cap was
    already reached. Any write error is logged at DEBUG and swallowed.
    """
    if not _is_enabled():
        return None

    exec_key = str(execution_id or "_adhoc")
    count = _FAILURE_COUNTS.get(exec_key, 0)
    cap = _failure_cap()
    if count >= cap:
        if count == cap:
            log.warning(
                "fb_failure_bundle: cap %d reached for execution %s; further "
                "bundles suppressed",
                cap,
                exec_key,
            )
            _FAILURE_COUNTS[exec_key] = count + 1  # one-shot warn
        return None
    _FAILURE_COUNTS[exec_key] = count + 1

    try:
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        bundle_dir = _bundle_root() / exec_key / f"{step_idx:03d}_{ts}_{reason}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # 1. XML (gzipped)
        if xml:
            xml_path = bundle_dir / "hierarchy.xml.gz"
            with gzip.open(xml_path, "wb") as fh:
                fh.write(xml.encode("utf-8", errors="replace"))

        # 2. Screenshot if device exposes one.
        try:
            shot_fn = getattr(device, "take_screenshot", None)
            if callable(shot_fn):
                jpg_bytes = shot_fn()
                if jpg_bytes:
                    (bundle_dir / "screen.jpg").write_bytes(jpg_bytes)
        except Exception as shot_exc:
            log.debug("fb_failure_bundle: screenshot capture failed: %s", shot_exc)

        # 3. Diagnostic
        if diagnostic is not None:
            (bundle_dir / "parse_diagnostic.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # 4. Step context snapshot (counts only)
        (bundle_dir / "step_context.json").write_text(
            json.dumps(_safe_step_ctx_snapshot(ctx), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 5. Traceback if exception
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            (bundle_dir / "traceback.txt").write_text(tb, encoding="utf-8")

        log.info(
            "fb_failure_bundle: wrote %s (reason=%s)",
            bundle_dir,
            reason,
        )
        return str(bundle_dir)
    except Exception as exc_write:
        log.debug("fb_failure_bundle: bundle write failed: %s", exc_write)
        return None


def reset_failure_counter(execution_id: Optional[str]) -> None:
    """Reset per-execution bundle count (call at scenario start)."""
    _FAILURE_COUNTS.pop(str(execution_id or "_adhoc"), None)
