#!/usr/bin/env python3
"""
Group-feed walk: MCP hierarchy + multi-post fb_posts from feed recycler,
cross-checked against per-card XML nodes. Optional one-post open + comment pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SERIAL_DEFAULT = "10AE7S00HD002JK"
OUT_DIR = _ROOT / "debug" / "traces" / "walk_reports"

# Toolbar / group chrome — not a post author on feed cards.
_GROUP_TOOLBAR_NAMES = frozenset({"openclaw vn", "openclaw"})


def _mcp_hierarchy(serial: str, refresh: bool = True) -> tuple[str | None, dict[str, Any]]:
    import urllib.request

    base = os.environ.get("DEVICE_FARM_URL", "http://localhost:8081").rstrip("/")
    token = (os.environ.get("MCP_AUTH_TOKEN") or "").strip()
    suffix = "?refresh=1" if refresh else ""
    url = f"{base}/api/devices/{serial}/hierarchy{suffix}"
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml = resp.read().decode("utf-8", errors="ignore")
        stripped = xml.strip()
        ok = stripped.startswith("<hierarchy") or stripped.startswith("<?xml")
        return (xml if ok else None), {"source": "mcp_http", "ok": ok, "bytes": len(xml)}
    except Exception as exc:
        return None, {"source": "mcp_http", "ok": False, "error": str(exc)}


def _feed_recycler_candidates(xml: str) -> list[tuple[int, str]]:
    """Return (feed_item_index, subtree_xml) for each recycler post card."""
    from relay.extra_data.parsers.facebook.feed_pipeline import _is_ad_container
    from relay.extra_data.parsers.facebook.parser import (
        _hierarchy_is_fb_comment_sheet,
        _parse_xml,
        _pick_feed_container,
        _recycler_item_top_y_sort_key,
    )
    from relay.extra_data.parsers.facebook.shared import XPATH_LIST, XPATH_RECYCLER

    root = _parse_xml(xml)
    if root is None:
        return []
    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return []
    feed = _pick_feed_container(containers, root)
    candidates = feed.findall("node")
    if not candidates:
        return []
    candidates = sorted(candidates, key=_recycler_item_top_y_sort_key)
    in_comment_sheet = _hierarchy_is_fb_comment_sheet(root)
    out: list[tuple[int, str]] = []
    idx = 0
    for candidate in candidates:
        if _is_ad_container(candidate):
            continue
        if in_comment_sheet:
            has_post_menu = False
            has_share_action = False
            for n in candidate.iter():
                t = (n.get("text") or "").strip()
                d = (n.get("content-desc") or "").strip()
                merged = f"{t} {d}".strip().lower()
                if not merged:
                    continue
                if "lựa chọn khác cho bài viết" in merged or "other options for post" in merged:
                    has_post_menu = True
                if "nút chia sẻ" in merged or merged == "chia sẻ":
                    has_share_action = True
                if has_post_menu and has_share_action:
                    break
            if not (has_post_menu or has_share_action):
                continue
        from lxml import etree

        frag = etree.tostring(candidate, encoding="unicode")
        out.append((idx, frag))
        idx += 1
    return out


def _authors_in_subtree(subtree_xml: str) -> list[str]:
    names: list[str] = []
    for m in re.finditer(r'(?:text|content-desc)="([^"]{2,80})"', subtree_xml):
        t = m.group(1).strip()
        if "•" in t or "chia sẻ với" in t.lower():
            continue
        if t.lower() in _GROUP_TOOLBAR_NAMES:
            continue
        if re.match(r"^\d+\s*(giờ|phút|ngày|thg)", t, re.I):
            continue
        if "lựa chọn khác" in t.lower() or "bình luận" == t.lower():
            continue
        if len(t) >= 2 and t not in names:
            names.append(t)
    return names


def _text_in_subtree(needle: str, subtree_xml: str, *, min_len: int = 12) -> bool:
    n = (needle or "").strip()
    if len(n) < min_len:
        return True
    chunk = re.sub(r"\s+", " ", n)[:48]
    flat = re.sub(r"\s+", " ", subtree_xml)
    return chunk.lower() in flat.lower()


def _body_evidence_in_subtree(body: str, subtree_xml: str) -> bool:
    """Body may merge duplicate nodes; any substantive phrase in XML counts."""
    flat = re.sub(r"\s+", " ", (subtree_xml or "")).lower()
    b = re.sub(r"\s+", " ", (body or "").strip())
    if not b:
        return False
    if b.lower() in flat:
        return True
    for part in re.split(r"\.\.|…", b):
        p = part.strip()
        if len(p) >= 14 and p.lower() in flat:
            return True
    for n in range(min(10, len(b.split())), 2, -1):
        chunk = " ".join(b.split()[:n])
        if len(chunk) >= 14 and chunk.lower() in flat:
            return True
    return False


def verify_post_against_recycler_node(
    post: dict[str, Any],
    subtree_xml: str,
    *,
    feed_item_index: int,
) -> list[str]:
    issues: list[str] = []
    author = (post.get("author") or "").strip()
    body = (post.get("text") or post.get("body") or "").strip()
    pid = post.get("_pid") or post.get("post_key")

    if author.lower() in _GROUP_TOOLBAR_NAMES:
        issues.append(f"feed[{feed_item_index}]:author_is_group_toolbar({author!r})")

    subtree_authors = _authors_in_subtree(subtree_xml)
    if author:
        if not _text_in_subtree(author, subtree_xml, min_len=2):
            issues.append(
                f"feed[{feed_item_index}]:author_not_in_card_xml(got={author!r},"
                f" card_names={subtree_authors[:4]!r})"
            )
        elif subtree_authors and author not in subtree_authors:
            # Allow partial match (FB truncates names)
            if not any(author in a or a in author for a in subtree_authors):
                issues.append(
                    f"feed[{feed_item_index}]:author_not_among_card_names"
                    f"(got={author!r}, card={subtree_authors[:3]!r})"
                )

    if body and not _body_evidence_in_subtree(body, subtree_xml):
        issues.append(f"feed[{feed_item_index}]:body_not_in_card_xml(prefix={body[:40]!r})")

    if author.lower() in ("ảnh", "photo", "image") and len(body) < 12:
        issues.append(f"feed[{feed_item_index}]:junk_comment_preview_card")

    if not author and not body:
        issues.append(f"feed[{feed_item_index}]:empty_post")

    if post.get("_incomplete") and body:
        issues.append(f"feed[{feed_item_index}]:incomplete_flag")

    if not pid:
        issues.append(f"feed[{feed_item_index}]:missing_pid")

    return issues


def _is_junk_extracted_post(post: dict[str, Any]) -> bool:
    author = (post.get("author") or "").strip().lower()
    body = (post.get("text") or "").strip()
    if author in ("ảnh", "photo", "image") and len(body) < 12:
        return True
    if not author and not body:
        return True
    return False


def verify_feed_posts_against_xml(
    posts: list[dict[str, Any]],
    feed_xml: str,
    *,
    min_posts: int,
) -> dict[str, Any]:
    from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic

    posts = [p for p in posts if isinstance(p, dict) and p.get("_type") != "post_stats"]
    candidates = _feed_recycler_candidates(feed_xml)
    _, diag = parse_fb_posts_from_xml_with_diagnostic(feed_xml, 0)

    all_issues: list[str] = []
    per_post: list[dict[str, Any]] = []

    valid_posts = [p for p in posts if not _is_junk_extracted_post(p)]
    if len(valid_posts) < min_posts:
        all_issues.append(
            f"too_few_valid_posts: valid={len(valid_posts)} parsed={len(posts)} need>={min_posts}"
        )

    if diag.get("path") != "recycler":
        all_issues.append(f"parse_path_not_recycler: {diag.get('path')}")

    by_index: dict[int, dict[str, Any]] = {}
    for p in posts:
        fi = p.get("feed_item_index")
        if isinstance(fi, int):
            by_index[fi] = p

    for fi, frag in candidates:
        post = by_index.get(fi)
        entry: dict[str, Any] = {
            "feed_item_index": fi,
            "has_extracted_post": post is not None,
            "subtree_bytes": len(frag.encode("utf-8")),
            "card_author_hints": _authors_in_subtree(frag)[:6],
        }
        if post is None:
            # Card visible but not parsed — only warn if card looks like a post
            if "lựa chọn khác cho bài viết" in frag or "Other options for post" in frag:
                all_issues.append(f"feed[{fi}]:recycler_card_not_extracted")
                entry["issues"] = ["recycler_card_not_extracted"]
            per_post.append(entry)
            continue
        issues = verify_post_against_recycler_node(post, frag, feed_item_index=fi)
        entry["issues"] = issues
        entry["author"] = (post.get("author") or "")[:50]
        entry["text_preview"] = (post.get("text") or "")[:72]
        entry["_pid"] = post.get("_pid")
        per_post.append(entry)
        all_issues.extend(issues)

    # Extracted post with no recycler slot
    for p in posts:
        fi = p.get("feed_item_index")
        if isinstance(fi, int) and fi >= len(candidates):
            all_issues.append(f"feed[{fi}]:index_out_of_recycler_range")

    return {
        "diag": diag,
        "recycler_cards": len(candidates),
        "posts_parsed": len(posts),
        "valid_posts": len(valid_posts),
        "per_post": per_post,
        "issues": all_issues,
        "ok": not all_issues,
    }


def _validate_comments(items: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if not items:
        issues.append("no_comments_extracted")
        return issues
    for i, c in enumerate(items[:15]):
        body = (c.get("text") or c.get("body") or "").strip()
        author = (c.get("author") or "").strip()
        if not body and not author:
            issues.append(f"comment[{i}]:empty")
        if body.startswith("Có thể là hình ảnh") and not author:
            issues.append(f"comment[{i}]:image_alt_not_comment")
    return issues


async def _ensure_group_feed(
    executor: Any,
    serial: str,
    *,
    min_posts: int,
    max_backs: int = 8,
) -> dict[str, Any]:
    from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic
    from relay.extra_data.parsers.facebook.parser import (
        _hierarchy_is_fb_comment_sheet,
        _parse_xml,
    )
    from relay.extra_data.parsers.facebook import post_open_pipeline as pop

    meta: dict[str, Any] = {"backs": 0, "min_posts": min_posts}

    def _screen_state(xml: str) -> dict[str, Any]:
        root = _parse_xml(xml)
        on_sheet = bool(root is not None and _hierarchy_is_fb_comment_sheet(root))
        on_detail = pop.hierarchy_is_fb_post_detail_from_xml(xml)
        posts, diag = parse_fb_posts_from_xml_with_diagnostic(xml, 0)
        posts = [p for p in posts if p.get("_type") != "post_stats" and not p.get("_soft_junk")]
        valid_n = sum(1 for p in posts if not _is_junk_extracted_post(p))
        return {
            "on_comment_sheet": on_sheet,
            "on_post_detail": on_detail,
            "feed_posts": len(posts),
            "valid_feed_posts": valid_n,
            "parse_path": diag.get("path"),
        }

    for attempt in range(max_backs + 1):
        xml = await _dump_via_executor(executor, serial)
        if not xml:
            meta["error"] = "dump_failed"
            return meta
        st = _screen_state(xml)
        meta.update(st)
        if (
            not st["on_comment_sheet"]
            and not st["on_post_detail"]
            and st.get("valid_feed_posts", 0) >= min_posts
            and st.get("parse_path") == "recycler"
        ):
            meta["ready"] = True
            return meta
        if st["on_comment_sheet"] or st["on_post_detail"] or "Bài viết của" in xml:
            await _key_back(executor, serial)
            meta["backs"] += 1
            await asyncio.sleep(0.55)
            continue
        if st["feed_posts"] < min_posts:
            await _swipe_feed(executor, serial)
            meta["swipes"] = meta.get("swipes", 0) + 1
            await asyncio.sleep(0.9)
            continue
        meta["ready"] = True
        return meta

    meta["ready"] = False
    return meta


async def _swipe_feed(executor: Any, serial: str) -> None:
    await executor.run_batch(
        serial,
        [{
            "op": "swipe",
            "x1": 0.18,
            "y1": 0.65,
            "x2": 0.18,
            "y2": 0.47,
            "duration_ms": 400,
        }],
    )


async def _key_back(executor: Any, serial: str) -> None:
    await executor.run_batch(serial, [{"op": "press", "key": "back"}])
    await asyncio.sleep(0.55)


def _make_executor(loop: asyncio.AbstractEventLoop) -> tuple[Any, Any]:
    from relay.u2_executor import U2Executor
    from relay.u2_session_pool import U2SessionPool

    pool = U2SessionPool(loop=loop)

    def _http_dump(s: str, timeout: float, compressed: bool = False) -> str:
        xml, _ = _mcp_hierarchy(s, refresh=True)
        return xml or ""

    executor = U2Executor(pool=pool, loop=loop, http_dump=_http_dump)
    return pool, executor


async def run_walk(
    serial: str,
    *,
    min_posts: int = 2,
    do_comment_pass: bool = True,
    allow_navigation: bool = False,
) -> dict[str, Any]:
    from relay.extra_data.collector import (
        collect_fb_comment_filter_apply,
        collect_fb_comment_target_with_tap,
        collect_xml_snapshots,
    )
    from relay.extra_data.ingest import _parse_items
    from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic
    from relay.extra_data.parsers.facebook import post_open_pipeline as pop

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    pool, executor = _make_executor(loop)
    await pool.start()

    report: dict[str, Any] = {
        "serial": serial,
        "min_posts": min_posts,
        "allow_navigation": allow_navigation,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "steps": {},
        "summary": {"ok": True, "failures": []},
    }

    def _fail(code: str) -> None:
        report["summary"]["ok"] = False
        report["summary"]["failures"].append(code)

    if allow_navigation:
        report["steps"]["ensure_feed"] = await _ensure_group_feed(
            executor, serial, min_posts=min_posts
        )
        if not report["steps"]["ensure_feed"].get("ready"):
            _fail("feed_not_ready")
    else:
        report["steps"]["ensure_feed"] = {
            "skipped": True,
            "reason": "allow_navigation=false — không back/swipe",
        }

    # ── 2) MCP hierarchy = nguồn truth cho extra fb_posts ───────────────
    feed_xml, mcp_meta = _mcp_hierarchy(serial, refresh=True)
    report["steps"]["mcp_hierarchy_feed"] = mcp_meta
    if not feed_xml:
        _fail("mcp_hierarchy_failed")
        await pool.stop()
        _write_report(report, serial)
        return report

    feed_path = OUT_DIR / "feed_multi.xml"
    feed_path.write_text(feed_xml, encoding="utf-8")
    report["steps"]["feed_xml"] = str(feed_path)

    # ── 3) Parse NHIỀU bài từ feed (KHÔNG open_post_before_extract) ─────
    posts, parse_diag = parse_fb_posts_from_xml_with_diagnostic(feed_xml, 0)
    posts = [p for p in posts if p.get("_type") != "post_stats" and not p.get("_soft_junk")]

    node_verify = verify_feed_posts_against_xml(
        posts, feed_xml, min_posts=min_posts
    )
    report["steps"]["feed_posts_extract"] = {
        "count": len(posts),
        "parse_diag": parse_diag,
        "recycler_cards": node_verify["recycler_cards"],
        "node_verify_ok": node_verify["ok"],
        "node_verify_issues": node_verify["issues"],
        "per_post": node_verify["per_post"],
        "posts_summary": [
            {
                "feed_item_index": p.get("feed_item_index"),
                "author": (p.get("author") or "")[:40],
                "text": (p.get("text") or "")[:72],
                "_pid": p.get("_pid"),
            }
            for p in posts
        ],
    }
    if not node_verify["ok"]:
        for issue in node_verify["issues"][:8]:
            _fail(f"feed_posts:{issue}")

    # ── 4) Tap mở bài đầu (post_open) — kiểm tra timestamp, không ảnh ───
    top, _ranked = pop.resolve_post_open_targets_from_xml(feed_xml)
    open_check: dict[str, Any] = {}
    if top:
        cx, cy = pop.post_header_tap_point(
            tuple(top["bounds"]),
            tap_kind=str(top.get("tap_kind") or ""),
        )
        open_check = {
            "tap_kind": top.get("tap_kind"),
            "bounds": top.get("bounds"),
            "label": (top.get("tap_label") or "")[:80],
            "tap_point": [cx, cy],
        }
        if top.get("tap_kind") == "post_media":
            _fail("post_open:tap_is_post_media")
    else:
        _fail("post_open:no_target")
    report["steps"]["post_open_resolve"] = open_check

    if not do_comment_pass or not allow_navigation:
        if not allow_navigation and do_comment_pass:
            report["steps"]["comment_pass"] = {
                "skipped": True,
                "reason": "Bật --allow-nav để tự tap/back (mặc định tắt)",
            }
        await pool.stop()
        _write_report(report, serial)
        return report

    # ── 5) Một vòng: mở bài[0] → extract detail → back → comment (chỉ khi --allow-nav)
    post_ctx: dict[str, Any] = {
        "open_post_before_extract": True,
        "open_post_verify": True,
        "open_post_tap_settle_s": 0.75,
        "expand_see_more": True,
        "expand_see_more_max_passes": 2,
        "expand_see_more_xml_probe_first": True,
        "locked_post_key": posts[0].get("post_key") if posts else None,
        "locked_stable_post_id": posts[0].get("stable_post_id") if posts else None,
    }
    snapshots, err = await collect_xml_snapshots(executor, serial, "fb_posts", post_ctx)
    report["steps"]["detail_extract"] = {
        "error": err,
        "snapshots": len(snapshots),
        "open_diag": post_ctx.get("open_post_detail_diagnostic"),
    }
    if snapshots:
        detail_xml = snapshots[-1]
        (OUT_DIR / "post_detail.xml").write_text(detail_xml, encoding="utf-8")
        detail_posts, _ = _parse_items("fb_posts", detail_xml, post_ctx)
        detail_posts = [p for p in detail_posts if p.get("_type") != "post_stats"]
        true_author = None
        m = re.search(r'content-desc="Bài viết của ([^"]+)"', detail_xml)
        if m:
            true_author = m.group(1).strip()
        detail_issues: list[str] = []
        if detail_posts:
            da = (detail_posts[0].get("author") or "").strip()
            if true_author and da != true_author:
                detail_issues.append(f"detail_author_mismatch(got={da!r},expected={true_author!r})")
        report["steps"]["detail_extract"]["detail_posts"] = len(detail_posts)
        report["steps"]["detail_extract"]["detail_issues"] = detail_issues
        for issue in detail_issues:
            _fail(issue)

    await _key_back(executor, serial)
    await asyncio.sleep(0.6)

    comment_ctx: dict[str, Any] = {
        "comment_target_verify": True,
        "post_tap_wait_s": 0.65,
        "comment_scroll_passes": 8,
        "comment_swipes_per_dump": 2,
        "min_comment_scan_passes": 2,
        "comment_no_growth_break": 4,
        "max_items": 120,
        "parent_post_id": posts[0].get("_pid") if posts else None,
    }

    _, _snap, tapped, tap_diag = await collect_fb_comment_target_with_tap(
        executor, serial, comment_ctx
    )
    report["steps"]["comment_target_tap"] = {
        "tapped": tapped,
        "verified": tap_diag.get("verified"),
        "reason": tap_diag.get("reason_code"),
        "target_pid": (tap_diag.get("target") or {}).get("pid"),
    }
    if not tap_diag.get("verified"):
        _fail("comment_tap_not_verified")

    filt_ctx = dict(comment_ctx)
    filt_ctx["switch_to_all_comments"] = True
    filt_out, filt_err = await collect_fb_comment_filter_apply(executor, serial, filt_ctx)
    report["steps"]["comment_filter"] = {"error": filt_err, "result": filt_out}

    csnap, cerr = await collect_xml_snapshots(executor, serial, "fb_comments", comment_ctx)
    report["steps"]["collect_fb_comments"] = {
        "error": cerr,
        "snapshots": len(csnap),
    }
    if csnap:
        (OUT_DIR / "comments.xml").write_text(csnap[-1], encoding="utf-8")
        comments, cdiag = _parse_items("fb_comments", csnap[-1], comment_ctx)
        c_issues = _validate_comments(comments)
        report["steps"]["parse_fb_comments"] = {
            "count": len(comments),
            "diag": cdiag,
            "issues": c_issues,
        }
        for issue in c_issues:
            _fail(f"comments:{issue}")

    await _key_back(executor, serial)
    await pool.stop()
    _write_report(report, serial)
    return report


def _write_report(report: dict[str, Any], serial: str) -> None:
    out_path = OUT_DIR / f"walk_{serial}_{int(time.time())}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(out_path)


async def _dump_via_executor(executor: Any, serial: str) -> str | None:
    from relay.extra_data.collector import _dump_hierarchy

    return await _dump_hierarchy(executor, serial, {})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default=SERIAL_DEFAULT)
    parser.add_argument("--min-posts", type=int, default=2)
    parser.add_argument("--feed-only", action="store_true", help="Skip open/comment pass")
    parser.add_argument(
        "--allow-nav",
        action="store_true",
        help="Cho phép back/swipe/tap tự động (mặc định: chỉ đọc hierarchy)",
    )
    args = parser.parse_args()

    report = asyncio.run(
        run_walk(
            args.serial,
            min_posts=max(2, args.min_posts),
            do_comment_pass=not args.feed_only,
            allow_navigation=args.allow_nav,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("summary", {}).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
