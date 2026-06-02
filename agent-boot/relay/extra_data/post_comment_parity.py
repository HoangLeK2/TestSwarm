"""Post ↔ comment extra-data parity checks and diagram output (no device navigation)."""

from __future__ import annotations

import re
from typing import Any

from relay.extra_data.capture_post_comment_verify import (
    resolve_production_parent_pid,
)
from relay.extra_data.parsers.facebook import (
    parse_fb_comments_from_xml_with_diagnostic,
    parse_fb_posts_from_xml_with_diagnostic,
)
from relay.extra_data.parsers.facebook.parser import (
    _hierarchy_is_fb_comment_sheet,
    _parse_xml,
)
from relay.extra_data.parsers.facebook import post_open_pipeline as pop

# Opening post: timestamp / header gap only — not photo or caption body.
_UNSAFE_POST_OPEN_TAP_KINDS = frozenset({"post_media", "post_body"})


def sheet_header_author_from_xml(xml: str) -> str | None:
    m = re.search(r'content-desc="Bài viết của ([^"]+)"', xml)
    if m:
        return m.group(1).strip()
    return None


def audit_feed_post_open_taps(xml: str, *, max_cards: int = 8) -> list[dict[str, Any]]:
    """Per visible card: which tap would fire and whether it is safe (ảnh/tên/body = NG)."""
    root = _parse_xml(xml)
    rows: list[dict[str, Any]] = []
    if root is None:
        return rows
    for feed_item_index, element in pop._discover_post_open_scan_elements(root):
        if len(rows) >= max_cards:
            break
        cand = pop._build_post_open_candidate(element, feed_item_index=feed_item_index)
        if cand is None:
            continue
        post = cand.get("post") or {}
        kind = str(cand.get("tap_kind") or "")
        bounds = cand.get("bounds")
        label = (cand.get("tap_label") or "")[:72]
        unsafe = kind in _UNSAFE_POST_OPEN_TAP_KINDS
        rows.append(
            {
                "rank": len(rows),
                "feed_item_index": post.get("feed_item_index", feed_item_index),
                "author": (post.get("author") or "")[:48],
                "tap_kind": kind,
                "tap_label": label,
                "bounds": bounds,
                "safe_for_post_open": not unsafe,
                "issue": f"unsafe_tap_{kind}" if unsafe else None,
            }
        )
    return rows


def verify_post_comment_parity(
    *,
    feed_post: dict[str, Any],
    comment_xml: str,
    session_tap_pid: str | None = None,
) -> dict[str, Any]:
    """
    Comment extra rows must attach to the same post as feed extract.
    Sheet chrome author must match feed author when present.
    """
    issues: list[str] = []
    expected_pid = str(feed_post.get("_pid") or feed_post.get("post_key") or "")
    expected_author = (feed_post.get("author") or "").strip()

    root = _parse_xml(comment_xml)
    on_sheet = bool(root is not None and _hierarchy_is_fb_comment_sheet(root))
    if not on_sheet:
        issues.append("not_on_comment_sheet")

    production_pid, pid_source = resolve_production_parent_pid(
        comment_xml, session_tap_pid=session_tap_pid or expected_pid
    )
    if not production_pid:
        issues.append(f"no_parent_pid(source={pid_source})")
    elif str(production_pid) != expected_pid:
        issues.append(
            f"parent_pid_mismatch(feed={expected_pid!r},sheet={production_pid!r},source={pid_source})"
        )

    sheet_author = sheet_header_author_from_xml(comment_xml)
    if sheet_author and expected_author and sheet_author != expected_author:
        if sheet_author not in expected_author and expected_author not in sheet_author:
            issues.append(
                f"author_mismatch(feed={expected_author!r},sheet={sheet_author!r})"
            )

    comments, cdiag = parse_fb_comments_from_xml_with_diagnostic(
        comment_xml, session_tap_pid or expected_pid
    )
    bodies = [c for c in comments if c.get("_type") != "post_stats"]
    wrong_parent = [
        c
        for c in bodies
        if str(c.get("parent_post_id") or "") not in ("", expected_pid)
        and str(c.get("parent_post_id") or "") != str(production_pid or "")
    ]
    if wrong_parent:
        issues.append(f"comment_rows_wrong_parent:{len(wrong_parent)}/{len(bodies)}")

    unique_parents = {str(c.get("parent_post_id") or "") for c in bodies if c.get("parent_post_id")}
    if len(unique_parents) > 1:
        issues.append(f"multiple_comment_parent_pids:{sorted(unique_parents)}")

    return {
        "ok": not issues,
        "issues": issues,
        "expected_pid": expected_pid,
        "production_pid": production_pid,
        "pid_source": pid_source,
        "feed_author": expected_author,
        "sheet_author": sheet_author,
        "comment_count": len(bodies),
        "comment_diag": cdiag.get("reason_code"),
        "on_comment_sheet": on_sheet,
    }


def mermaid_parity_diagram(
    *,
    feed_posts: list[dict[str, Any]],
    tap_audit: list[dict[str, Any]],
    parity: dict[str, Any] | None,
    screen: str,
) -> str:
    """Mermaid flow: feed post node must equal comment parent + sheet author."""
    lines = ["```mermaid", "flowchart TB"]
    lines.append(f'  screen["Màn hình: {screen}"]')

    for i, p in enumerate(feed_posts[:4]):
        pid = (p.get("_pid") or "?")[:12]
        author = (p.get("author") or "?")[:24].replace('"', "'")
        fi = p.get("feed_item_index", i)
        lines.append(f'  FP{fi}["feed post #{fi}<br/>{author}<br/>_pid={pid}…"]')

    for t in tap_audit[:3]:
        fi = t.get("feed_item_index", 0)
        kind = t.get("tap_kind", "?")
        safe = "OK" if t.get("safe_for_post_open") else "NG"
        lines.append(f'  TAP{fi}["Card #{fi} mở bài: {kind}<br/>{safe}"]')
        lines.append(f"  FP{fi} --> TAP{fi}")

    if parity:
        ok = parity.get("ok")
        status = "khớp" if ok else "LỖI"
        lines.append(f'  PAR["Post ↔ Comment: {status}"]')
        if feed_posts:
            lines.append(f"  FP{feed_posts[0].get('feed_item_index', 0)} --> PAR")
        lines.append(
            f'  CS["sheet _pid={str(parity.get("production_pid") or "?")[:12]}…<br/>'
            f'author={parity.get("sheet_author") or "?"}"]'
        )
        lines.append("  PAR --> CS")
        for issue in (parity.get("issues") or [])[:4]:
            safe_issue = issue.replace('"', "'")[:60]
            lines.append(f'  PAR -.->|"{safe_issue}"| ERR{hash(issue) % 9}[" "]')

    lines.append("```")
    return "\n".join(lines)


def classify_screen(xml: str) -> str:
    root = _parse_xml(xml)
    if root is not None and pop._hierarchy_has_post_detail_chrome(root):
        return "post_detail"
    if root is not None and _hierarchy_is_fb_comment_sheet(root):
        return "comment_sheet"
    if pop.hierarchy_is_fb_post_detail_from_xml(xml):
        return "post_detail"
    posts, diag = parse_fb_posts_from_xml_with_diagnostic(xml, 0)
    if diag.get("path") == "recycler" and posts:
        return "group_feed"
    return "unknown"
