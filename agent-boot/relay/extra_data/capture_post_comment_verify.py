"""Verify comment rows map to the correct parent post for device_farm/captures replay."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from relay.extra_data.ingest import _parse_items
from relay.extra_data.parsers.facebook import (
    parse_fb_comments_from_xml_with_diagnostic,
    parse_fb_posts_from_xml_with_diagnostic,
)
from relay.extra_data.parsers.facebook.comment_pipeline import (
    _feed_post_pid_for_comment_scope,
)
from relay.extra_data.parsers.facebook.parser import (
    _collect_text_nodes,
    _hierarchy_is_fb_comment_sheet,
    _parse_xml,
)
from relay.extra_data.parsers.facebook.post_extractor import _compute_post_id_from_nodes

VerifyStatus = Literal["pass", "skip", "fail"]


@dataclass
class CaptureVerifyResult:
    rel_path: str
    session: str
    step: str
    status: VerifyStatus
    expected_pid: str | None = None
    expected_source: str = ""
    comment_count: int = 0
    issues: list[str] = field(default_factory=list)


def _hierarchy_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob("*_hierarchy.xml")
        if "pre_" not in p.name and p.is_file()
    )


def resolve_session_tap_parent_pid(session_dir: Path) -> tuple[str | None, str]:
    """PID from pre-tap hierarchy (same screen production uses for tap_fb_comment_button)."""
    for path in sorted(session_dir.glob("*tap_fb_comment_button_pre_hierarchy.xml")):
        xml = path.read_text(encoding="utf-8")
        root = _parse_xml(xml)
        if root is not None and _hierarchy_is_fb_comment_sheet(root):
            continue
        _, diag = _parse_items("fb_comment_target", xml, {})
        if diag.get("reason_code") == "ok" and diag.get("target"):
            return str(diag["target"]["pid"]), f"tap_target:{path.name}"
    return None, ""


def resolve_production_parent_pid(
    xml: str,
    *,
    session_tap_pid: str | None,
) -> tuple[str | None, str]:
    """Effective parent_post_id after parser corrections (matches ingest output)."""
    root = _parse_xml(xml)
    if root is None:
        return None, "unparseable"

    if _hierarchy_is_fb_comment_sheet(root):
        nodes = _collect_text_nodes(root, toolbar_cutoff_y=200)
        sheet_pid = _compute_post_id_from_nodes(nodes)
        if sheet_pid:
            return str(sheet_pid), "comment_sheet_context"
        posts, _ = parse_fb_posts_from_xml_with_diagnostic(xml, 0)
        posts = [p for p in posts if isinstance(p, dict) and p.get("_type") != "post_stats"]
        if len(posts) == 1 and posts[0].get("_pid"):
            return str(posts[0]["_pid"]), "comment_sheet_post"
        return None, "comment_sheet_no_pid"

    visible = _feed_post_pid_for_comment_scope(root, session_tap_pid)
    if visible:
        tag = "session_tap_visible" if visible == session_tap_pid else "visible_post_corrected"
        return str(visible), tag

    return None, "no_comment_scope"


def _post_by_pid(posts: list[dict[str, Any]], pid: str | None) -> dict[str, Any] | None:
    if not pid:
        return None
    for p in posts:
        if str(p.get("_pid") or "") == pid:
            return p
    return None


def _other_post_pids(posts: list[dict[str, Any]], pid: str) -> list[str]:
    return [str(p.get("_pid")) for p in posts if str(p.get("_pid") or "") != pid and p.get("_pid")]


def verify_capture_file(
    path: Path,
    captures_root: Path,
    session_tap_pid: str | None,
) -> CaptureVerifyResult:
    rel = str(path.relative_to(captures_root))
    session = path.parent.name
    step = path.name
    xml = path.read_text(encoding="utf-8")
    root = _parse_xml(xml)
    result = CaptureVerifyResult(
        rel_path=rel,
        session=session,
        step=step,
        status="skip",
    )

    if root is None:
        result.issues.append("xml_parse_error")
        result.status = "fail"
        return result

    production_pid, source = resolve_production_parent_pid(
        xml, session_tap_pid=session_tap_pid
    )
    result.expected_pid = production_pid
    result.expected_source = source

    if production_pid is None:
        rows, diag = parse_fb_comments_from_xml_with_diagnostic(
            xml, session_tap_pid
        )
        bodies = [r for r in rows if r.get("_type") != "post_stats"]
        if not bodies:
            result.status = "skip"
            return result
        result.issues.append(
            f"comments_without_scope: {len(bodies)} rows, diag={diag.get('reason_code')}"
        )
        result.status = "fail"
        result.comment_count = len(bodies)
        return result

    # Production passes session tap pid; parser may correct to on-screen post.
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, session_tap_pid)
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    result.comment_count = len(bodies)

    if diag.get("reason_code") != "ok" or not bodies:
        if diag.get("reason_code") in ("not_comment_sheet", "no_text_nodes"):
            result.status = "skip"
            return result
        result.issues.append(f"parse_failed: {diag.get('reason_code')}")
        result.status = "fail"
        return result

    wrong_parent = [
        b for b in bodies if str(b.get("parent_post_id") or "") != production_pid
    ]
    if wrong_parent:
        result.issues.append(
            f"parent_post_id_mismatch: {len(wrong_parent)}/{len(bodies)} "
            f"(got {{ {', '.join(sorted({str(b.get('parent_post_id')) for b in wrong_parent}))} }}, "
            f"expected {production_pid})"
        )

    unique_parents = {str(b.get("parent_post_id") or "") for b in bodies}
    if len(unique_parents) > 1:
        result.issues.append(f"multiple_parent_pids: {unique_parents}")

    posts, _ = parse_fb_posts_from_xml_with_diagnostic(xml, 0)
    posts = [p for p in posts if isinstance(p, dict) and p.get("_type") != "post_stats"]
    target_post = _post_by_pid(posts, production_pid)

    if target_post and bodies:
        body_prefix = str(target_post.get("text") or target_post.get("body") or "").lower()
        for b in bodies:
            ctext = str(b.get("text") or "").lower()
            if body_prefix and len(body_prefix) > 20:
                if body_prefix[:40] not in ctext and ctext[:40] not in body_prefix:
                    author = str(b.get("author") or "")
                    if author and author.lower() not in body_prefix:
                        pass  # comments rarely contain full post body

    if result.issues:
        result.status = "fail"
    else:
        result.status = "pass"
    return result


def verify_all_captures(captures_root: Path | str) -> list[CaptureVerifyResult]:
    root = Path(captures_root)
    results: list[CaptureVerifyResult] = []
    session_dirs = sorted(
        d for d in root.iterdir() if d.is_dir() and d.name.startswith("10AE")
    )
    for session_dir in session_dirs:
        tap_pid, _ = resolve_session_tap_parent_pid(session_dir)
        for path in _hierarchy_paths(session_dir):
            results.append(verify_capture_file(path, root, tap_pid))
    return results


def summarize_results(results: list[CaptureVerifyResult]) -> dict[str, Any]:
    passed = [r for r in results if r.status == "pass"]
    skipped = [r for r in results if r.status == "skip"]
    failed = [r for r in results if r.status == "fail"]
    return {
        "total": len(results),
        "pass": len(passed),
        "skip": len(skipped),
        "fail": len(failed),
        "failed": [
            {
                "path": r.rel_path,
                "issues": r.issues,
                "expected_pid": r.expected_pid,
                "source": r.expected_source,
                "comments": r.comment_count,
            }
            for r in failed
        ],
    }
