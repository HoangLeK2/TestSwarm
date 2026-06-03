from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .constants import _AD_RESOURCE_IDS, _RE_LIKE_BTN_DESC, _RE_SHARES
from .shared import XPATH_LIST, XPATH_RECYCLER
from .dedup import _TRUNCATION_MARKERS


def _is_ad_container(element) -> bool:
    for node in element.iter():
        if (node.get("resource-id") or "") in _AD_RESOURCE_IDS:
            return True
    return False


def is_fb_post_truncated(post: Dict[str, Any]) -> bool:
    t = (post.get("text") or "").lower()
    return any(m in t for m in _TRUNCATION_MARKERS)


def _parse_stats(t: str) -> Dict[str, Optional[str]]:
    from .constants import _RE_COMMENTS, _RE_COMBINED_STATS, _RE_REACTIONS, _RE_SHARES, _RE_VIEWS

    result: Dict[str, Optional[str]] = {"reactions": None, "comments": None, "shares": None, "views": None}
    if "·" in t or "•" in t:
        parts = re.split(r"[·•]", t)
        for part in parts:
            _apply_stat(part.strip(), result, _RE_COMMENTS, _RE_REACTIONS, _RE_SHARES, _RE_VIEWS)
        return result
    _apply_stat(t, result, _RE_COMMENTS, _RE_REACTIONS, _RE_SHARES, _RE_VIEWS)
    return result


def _apply_stat(
    t: str,
    result: Dict[str, Optional[str]],
    re_comments,
    re_reactions,
    re_shares,
    re_views,
) -> None:
    m = _RE_LIKE_BTN_DESC.match(t)
    if m and result["reactions"] is None:
        result["reactions"] = m.group(1)
        return
    m = re_views.search(t)
    if m and result["views"] is None:
        result["views"] = m.group(1)
        return
    m = re_shares.search(t)
    if m and result["shares"] is None:
        result["shares"] = m.group(1)
        return
    m = re_comments.search(t)
    if m and result["comments"] is None:
        result["comments"] = m.group(1)
        return
    m = re_reactions.search(t)
    if m and result["reactions"] is None:
        label = (m.group(2) or "").lower()
        stripped = t.strip()
        if label:
            result["reactions"] = m.group(1)
        elif len(stripped) <= 8 and re.fullmatch(r"[^\d]*\d[\d.,]*[KMkm]?\s*", stripped, flags=re.IGNORECASE):
            result["reactions"] = m.group(1)


def _extract_posts_from_recycler(root, source_index: int) -> Optional[List[Dict[str, Any]]]:
    from .post_extractor import (
        _extract_fb_link_meta,
        _extract_media_artifacts,
        _extract_post,
        _merge_action_bar_stats,
        _resource_id_media_hint,
        _structural_post_type_hint,
        _maybe_fix_merged_feed_caption,
        _refresh_post_derived_hashes,
    )
    from .parser import (
        _collect_text_nodes,
        _hierarchy_is_fb_comment_sheet,
        _parse_bounds,
        _pick_feed_container,
        _recycler_item_top_y_sort_key,
    )
    from .filters import _is_junk_recycler_post, _keep_soft_junk

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return None
    in_comment_sheet = _hierarchy_is_fb_comment_sheet(root)
    feed = _pick_feed_container(containers, root)
    candidates = feed.findall("node")
    if not candidates:
        return None
    candidates = sorted(candidates, key=_recycler_item_top_y_sort_key)
    posts: List[Dict[str, Any]] = []
    for feed_item_index, candidate in enumerate(candidates):
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
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
        media_artifacts = _extract_media_artifacts(candidate)
        post = _extract_post(
            nodes,
            source_index,
            structural_type_hint=_structural_post_type_hint(candidate),
            resource_id_media_hint=_resource_id_media_hint(candidate),
            fb_post_id=fb_pid,
            fb_group_id=fb_gid,
            permalink_candidates=perms,
            feed_item_index=feed_item_index,
        )
        if post:
            card_bounds = _parse_bounds(candidate)
            if card_bounds:
                post["card_bounds"] = [
                    int(card_bounds[0]),
                    int(card_bounds[1]),
                    int(card_bounds[2]),
                    int(card_bounds[3]),
                ]
            _merge_action_bar_stats(post, candidate)
            _maybe_fix_merged_feed_caption(post)
            _refresh_post_derived_hashes(post)
            if media_artifacts:
                post["media_artifacts"] = media_artifacts
                if post.get("post_type") == "text":
                    post["post_type"] = "photo"
            if _is_junk_recycler_post(post):
                if _keep_soft_junk():
                    post["_soft_junk"] = True
                    posts.append(post)
                continue
            posts.append(post)

    if in_comment_sheet and not posts:
        nodes = _collect_text_nodes(feed, toolbar_cutoff_y=0)
        fb_pid, fb_gid, perms = _extract_fb_link_meta(feed)
        media_artifacts = _extract_media_artifacts(feed)
        post = _extract_post(
            nodes,
            source_index,
            structural_type_hint=_structural_post_type_hint(feed),
            resource_id_media_hint=_resource_id_media_hint(feed),
            fb_post_id=fb_pid,
            fb_group_id=fb_gid,
            permalink_candidates=perms,
            feed_item_index=0,
        )
        if post:
            _maybe_fix_merged_feed_caption(post)
            _refresh_post_derived_hashes(post)
            if media_artifacts:
                post["media_artifacts"] = media_artifacts
                if post.get("post_type") == "text":
                    post["post_type"] = "photo"
            if _is_junk_recycler_post(post):
                if _keep_soft_junk():
                    post["_soft_junk"] = True
                    posts.append(post)
            else:
                posts.append(post)
    return posts


def _empty_post_diagnostic(reason_code: str, **extra) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "reason_code": reason_code,
        "posts_returned": 0,
        "candidate_clusters": 0,
        "filtered_junk_count": 0,
        "truncated_post_count": 0,
        "locale_tokens_hit": [],
    }
    base.update(extra)
    return base


def parse_fb_posts_from_xml_with_diagnostic(
    xml: str,
    source_index: int = 0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from .clustering import _cluster_into_posts
    from .dedup import _dedup
    from .filters import _is_junk_recycler_post, _keep_soft_junk
    from .parser import _collect_text_nodes, _infer_screen_size, _parse_xml, _scan_special_screen, _hierarchy_is_fb_comment_sheet
    from .post_extractor import _extract_post, _maybe_fix_merged_feed_caption, _refresh_post_derived_hashes

    t0 = time.monotonic()
    root = _parse_xml(xml)
    if root is None:
        return [], _empty_post_diagnostic("xml_parse_error", elapsed_ms=round((time.monotonic() - t0) * 1000, 2))

    special = _scan_special_screen(root)
    if special:
        return [], _empty_post_diagnostic(special, elapsed_ms=round((time.monotonic() - t0) * 1000, 2))

    screen_w, screen_h = _infer_screen_size(root)
    posts = _extract_posts_from_recycler(root, source_index)
    if posts is not None:
        if posts:
            truncated_n = sum(1 for p in posts if is_fb_post_truncated(p))
            return posts, {
                "reason_code": "ok",
                "posts_returned": len(posts),
                "candidate_clusters": len(posts),
                "filtered_junk_count": 0,
                "truncated_post_count": truncated_n,
                "screen_size": [screen_w, screen_h],
                "locale_tokens_hit": [],
                "path": "recycler",
                "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
            }
        if _hierarchy_is_fb_comment_sheet(root):
            return [], _empty_post_diagnostic(
                "comment_sheet_no_posts_expected",
                screen_size=[screen_w, screen_h],
                elapsed_ms=round((time.monotonic() - t0) * 1000, 2),
            )

    nodes = _collect_text_nodes(root)
    clusters = _cluster_into_posts(nodes, screen_height=screen_h)
    result: List[Dict[str, Any]] = []
    junk_count = 0
    for cluster in clusters:
        post = _extract_post(cluster, source_index)
        if post:
            _maybe_fix_merged_feed_caption(post)
            _refresh_post_derived_hashes(post)
            if _is_junk_recycler_post(post):
                junk_count += 1
                if _keep_soft_junk():
                    post["_soft_junk"] = True
                    result.append(post)
            else:
                result.append(post)

    if not result:
        reason = "no_candidates" if not clusters else "all_filtered_junk"
        return [], _empty_post_diagnostic(
            reason,
            candidate_clusters=len(clusters),
            filtered_junk_count=junk_count,
            screen_size=[screen_w, screen_h],
            elapsed_ms=round((time.monotonic() - t0) * 1000, 2),
        )

    truncated_n = sum(1 for p in result if is_fb_post_truncated(p))
    return result, {
        "reason_code": "ok",
        "posts_returned": len(result),
        "candidate_clusters": len(clusters),
        "filtered_junk_count": junk_count,
        "truncated_post_count": truncated_n,
        "screen_size": [screen_w, screen_h],
        "locale_tokens_hit": [],
        "path": "cluster",
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
    }


def parse_fb_posts_from_xml(xml: str, source_index: int = 0) -> List[Dict[str, Any]]:
    posts, _ = parse_fb_posts_from_xml_with_diagnostic(xml, source_index)
    return posts


def _extract_header_stats(
    root,
    y_max: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    from .parser import _infer_screen_size, _parse_bounds

    _screen_w, screen_h = _infer_screen_size(root)
    if y_max is None or y_max <= 0:
        y_max = max(400, int(screen_h * 0.55))

    reactions: Optional[str] = None
    shares: Optional[str] = None
    comments_count: Optional[str] = None

    def _consume(t: str) -> None:
        nonlocal reactions, shares, comments_count
        if not t:
            return
        m_like = _RE_LIKE_BTN_DESC.match(t)
        if m_like and reactions is None:
            reactions = m_like.group(1)
            return
        if re.match(r"^\d[\d.,]*[KMkm]?$", t) and reactions is None:
            reactions = t
            return
        m_sh = _RE_SHARES.search(t)
        if m_sh and shares is None:
            shares = m_sh.group(1)
            return
        m_cm = re.search(r"(\d[\d.,]*[KMkm]?)\s*(bình luận|comments?)", t, re.IGNORECASE)
        if m_cm and comments_count is None:
            comments_count = m_cm.group(1)
        if reactions is None or shares is None:
            st = _parse_stats(t)
            if reactions is None and st.get("reactions"):
                reactions = st["reactions"]
            if shares is None and st.get("shares"):
                shares = st["shares"]

    for node in root.iter():
        bounds = _parse_bounds(node)
        if not bounds or bounds[1] > y_max:
            continue
        cls = node.get("class", "")
        clickable = (node.get("clickable") or "").lower() == "true"
        if "Button" not in cls and not clickable:
            continue
        t = (node.get("text") or "").strip()
        d = (node.get("content-desc") or "").strip()
        _consume(t)
        _consume(d)

    for node in root.iter():
        bounds = _parse_bounds(node)
        if not bounds or bounds[1] > y_max:
            continue
        t = (node.get("text") or "").strip()
        d = (node.get("content-desc") or "").strip()
        _consume(t)
        _consume(d)

    if reactions is None and shares is None and comments_count is None:
        return None
    stats: Dict[str, Any] = {"_type": "post_stats"}
    if reactions is not None:
        stats["reactions"] = reactions
    if shares is not None:
        stats["shares"] = shares
    if comments_count is not None:
        stats["comments"] = comments_count
    return stats


__all__ = [
    "_empty_post_diagnostic",
    "_extract_header_stats",
    "_extract_posts_from_recycler",
    "parse_fb_posts_from_xml",
    "parse_fb_posts_from_xml_with_diagnostic",
]

