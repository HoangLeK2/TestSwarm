from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    _MAX_TS_ANCHOR_NODE_LEN,
    _RE_CMT_REACTIONS,
    _RE_CMT_REACTIONS_EN,
    _RE_CMT_REPLY_BTN,
    _RE_CMT_TS_SHARE,
    _RE_TS,
    _RE_COMMENT_NAME_DOT_SUFFIX,
    _RE_CMT_LIKE_BTN,
)
from .shared import COMMENT_BUTTON_TOKENS, XPATH_LIST, XPATH_RECYCLER


def _post_id_from_ctx(ctx: Dict[str, Any], post_id_var: Optional[str]) -> Optional[str]:
    if post_id_var:
        return ctx.get(post_id_var)
    return None


def _extract_comment(
    cluster: List[Dict[str, Any]],
    parent_post_id: Optional[str] = None,
    cluster_min_x: int = 150,
) -> Optional[Dict[str, Any]]:
    from .filters import _comment_line_is_badge, _is_cmt_noise, _is_comment_image_placeholder_text
    from .post_extractor import _is_hashtag_chip, _refine_comment_author_from_cluster

    author: Optional[str] = None
    badges: List[str] = []
    body_parts: List[str] = []
    timestamp: Optional[str] = None
    likes: Optional[str] = None
    pending_badges: List[str] = []

    def _flush_pending_badges() -> None:
        nonlocal pending_badges
        if pending_badges:
            badges.extend(pending_badges)
            pending_badges = []

    for node in cluster:
        t = node["text"].strip()
        if not t or len(t) <= 1:
            continue
        m = _RE_CMT_LIKE_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            _flush_pending_badges()
            continue
        m = _RE_CMT_REPLY_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            _flush_pending_badges()
            continue
        if _is_cmt_noise(t):
            continue
        m = _RE_CMT_REACTIONS.match(t) or _RE_CMT_REACTIONS_EN.match(t)
        if m:
            likes = m.group(1)
            continue
        if _is_comment_image_placeholder_text(t):
            if not any(p.strip() == "[image]" for p in body_parts):
                body_parts.append("[image]")
            continue
        if author is None and _comment_line_is_badge(t):
            pending_badges.append(t.strip())
            continue
        if author is None and node.get("is_author_hint"):
            if 2 <= len(t) <= 90 and not _comment_line_is_badge(t):
                author = t
                _flush_pending_badges()
                continue
        m_dot = _RE_COMMENT_NAME_DOT_SUFFIX.match(t.strip())
        if author is None and m_dot:
            left, right = m_dot.group(1).strip(), m_dot.group(2).strip()
            if 2 <= len(left) <= 60:
                if _comment_line_is_badge(right):
                    author = left
                    badges.append(right.strip())
                    _flush_pending_badges()
                    continue
                if len(right) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(right):
                    author = left
                    clean_r = _RE_CMT_TS_SHARE.sub("", right).strip()
                    if timestamp is None:
                        timestamp = clean_r if clean_r else right
                    _flush_pending_badges()
                    continue
        if len(t) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(t):
            clean = _RE_CMT_TS_SHARE.sub("", t).strip()
            if timestamp is None:
                timestamp = clean if clean else t
            continue
        if author is None and 2 <= len(t) <= 80 and "·" not in t and "•" not in t and not _is_hashtag_chip(t):
            author = t
            _flush_pending_badges()
            continue
        if author is not None and _comment_line_is_badge(t):
            badges.append(t.strip())
            continue
        if author and unicodedata.normalize("NFC", t).lower() == unicodedata.normalize("NFC", author).lower():
            continue
        body_parts.append(t)

    if author and pending_badges:
        badges.extend(pending_badges)

    text = " ".join(body_parts).strip()
    author = _refine_comment_author_from_cluster(cluster, author)
    if not author and not text:
        return None

    norm_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    norm_text = unicodedata.normalize("NFC", text.strip().lower())
    norm_parent = unicodedata.normalize("NFC", (parent_post_id or "").strip().lower())
    comment_key = hashlib.sha1(f"{norm_parent}\x00{norm_author}\x00{norm_text}".encode("utf-8")).hexdigest()
    indent_level = 2 if cluster_min_x >= 280 else (1 if cluster_min_x >= 220 else 0)
    out: Dict[str, Any] = {
        "author": author or "",
        "text": text,
        "timestamp": timestamp,
        "likes": likes,
        "parent_post_id": parent_post_id,
        "indent_level": indent_level,
        "comment_key": comment_key,
    }
    if likes:
        out["reactions"] = likes
    if badges:
        seen_b: set[str] = set()
        deduped: List[str] = []
        for b in badges:
            k = unicodedata.normalize("NFC", (b or "").strip()).lower()
            if not k or k in seen_b:
                continue
            seen_b.add(k)
            deduped.append(b.strip())
        out["badges"] = deduped
    return out


def _find_binh_luan_button_in_element(element) -> Optional[Tuple[int, int, int]]:
    best: Optional[Tuple[int, int, int]] = None
    best_y1 = 10**9
    fallback: Optional[Tuple[int, int, int]] = None
    fallback_y1 = 10**9
    for node in element.iter():
        t = (node.get("text") or "").strip()
        d = (node.get("content-desc") or "").strip()
        if t not in COMMENT_BUTTON_TOKENS and d not in COMMENT_BUTTON_TOKENS:
            continue
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
        if not m:
            continue
        y1, y2 = int(m.group(2)), int(m.group(4))
        y_mid = (y1 + y2) // 2
        if "Button" in (node.get("class") or ""):
            if y1 < best_y1:
                best_y1 = y1
                best = (y1, y2, y_mid)
        elif node.get("clickable") == "true" and y1 < fallback_y1:
            fallback_y1 = y1
            fallback = (y1, y2, y_mid)
    return best or fallback


def _legacy_last_binh_luan_anchors(root) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    from .parser import _feed_comment_y_max

    action_btn_y2: Optional[int] = None
    action_btn_y_mid: Optional[int] = None
    for node in root.iter():
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        cls = node.get("class", "")
        if (text in COMMENT_BUTTON_TOKENS or desc in COMMENT_BUTTON_TOKENS) and "Button" in cls:
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
            if m:
                y1, y2 = int(m.group(2)), int(m.group(4))
                action_btn_y2 = y2
                action_btn_y_mid = (y1 + y2) // 2
    cy_max = _feed_comment_y_max(root, action_btn_y_mid)
    return action_btn_y2, action_btn_y_mid, cy_max


def _resolve_comment_region_anchors(root, row_match_pid: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    from .feed_pipeline import _is_ad_container
    from .post_extractor import (
        _extract_fb_link_meta,
        _extract_post,
        _resource_id_media_hint,
        _structural_post_type_hint,
    )
    from .parser import _collect_text_nodes, _hierarchy_is_fb_comment_sheet, _parse_bounds, _pick_feed_container

    if _hierarchy_is_fb_comment_sheet(root):
        return _legacy_last_binh_luan_anchors(root)

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return _legacy_last_binh_luan_anchors(root)

    feed = _pick_feed_container(containers, root)
    children = feed.findall("node")
    if not children:
        return _legacy_last_binh_luan_anchors(root)

    rows: List[Tuple[int, Optional[Dict[str, Any]], Optional[Tuple[int, int, int]], Optional[int]]] = []
    for feed_item_index, candidate in enumerate(children):
        if _is_ad_container(candidate):
            continue
        cb = _parse_bounds(candidate)
        y_top = cb[1] if cb else 10**9
        card_bottom = cb[3] if cb else None
        btn = _find_binh_luan_button_in_element(candidate)
        post: Optional[Dict[str, Any]] = None
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        if nodes:
            fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
            post = _extract_post(
                nodes,
                0,
                structural_type_hint=_structural_post_type_hint(candidate),
                resource_id_media_hint=_resource_id_media_hint(candidate),
                fb_post_id=fb_pid,
                fb_group_id=fb_gid,
                permalink_candidates=perms,
                feed_item_index=feed_item_index,
            )
        rows.append((y_top, post, btn, card_bottom))

    if row_match_pid:
        for _yt, post, btn, cbot in sorted(rows, key=lambda r: r[0]):
            if post and post.get("_pid") == row_match_pid and btn:
                _y1, y2, y_mid = btn
                return y2, y_mid, cbot

    with_btn = [(yt, post, btn, cbot) for yt, post, btn, cbot in rows if btn]
    if with_btn:
        with_btn.sort(key=lambda r: (r[0], r[2][0] if r[2] else 0))
        _yt, _post, btn, cbot = with_btn[0]
        _y1, y2, y_mid = btn
        return y2, y_mid, cbot

    return _legacy_last_binh_luan_anchors(root)


def _find_binh_luan_button_bounds_in_element(element) -> Optional[Tuple[int, int, int, int]]:
    best: Optional[Tuple[int, int, int, int]] = None
    best_y1 = 10**9
    fallback: Optional[Tuple[int, int, int, int]] = None
    fallback_y1 = 10**9
    for node in element.iter():
        t = (node.get("text") or "").strip()
        d = (node.get("content-desc") or "").strip()
        if t not in COMMENT_BUTTON_TOKENS and d not in COMMENT_BUTTON_TOKENS:
            continue
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
        if not m:
            continue
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if "Button" in (node.get("class") or ""):
            if y1 < best_y1:
                best_y1 = y1
                best = (x1, y1, x2, y2)
        elif node.get("clickable") == "true" and y1 < fallback_y1:
            fallback_y1 = y1
            fallback = (x1, y1, x2, y2)
    return best or fallback


def resolve_topmost_comment_target_from_xml(
    xml: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, int, int, int]]]:
    from .feed_pipeline import _is_ad_container
    from .post_extractor import (
        _extract_fb_link_meta,
        _extract_post,
        _resource_id_media_hint,
        _structural_post_type_hint,
    )
    from .parser import _collect_text_nodes, _parse_xml, _pick_feed_container

    root = _parse_xml(xml)
    if root is None:
        return None, None

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    feed_children = []
    if containers:
        feed = _pick_feed_container(containers, root)
        feed_children = feed.findall("node")

    scan_candidates: List[Tuple[int, Any]] = (
        [(i, c) for i, c in enumerate(feed_children) if not _is_ad_container(c)]
        if feed_children
        else [(0, root)]
    )

    best: Optional[Tuple[int, Dict[str, Any], Tuple[int, int, int, int]]] = None
    for feed_item_index, candidate in scan_candidates:
        btn = _find_binh_luan_button_bounds_in_element(candidate)
        if not btn:
            continue
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        if not nodes:
            continue
        fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
        post = _extract_post(
            nodes,
            0,
            structural_type_hint=_structural_post_type_hint(candidate),
            resource_id_media_hint=_resource_id_media_hint(candidate),
            fb_post_id=fb_pid,
            fb_group_id=fb_gid,
            permalink_candidates=perms,
            feed_item_index=feed_item_index,
        )
        if not post or not post.get("_pid"):
            continue
        y_top = btn[1]
        if best is None or y_top < best[0]:
            best = (y_top, post, btn)

    if best is None:
        return None, None
    _yt, post, btn = best
    return post, btn


def parse_fb_comments_from_xml_with_diagnostic(
    xml: str,
    parent_post_id: Optional[str] = None,
    max_items: int = 50,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from .clustering import _cluster_into_comments
    from .filters import (
        _is_comment_row_parse_noise,
        _is_duplicate_short_author_footer_row,
        _is_comment_reaction_count_row,
        _is_compact_comment_action_label,
        _is_comment_left_avatar_name_strip,
        _is_junk_parsed_comment_row,
    )
    from .parser import (
        _collect_text_nodes,
        _hierarchy_is_fb_comment_sheet,
        _infer_screen_size,
        _parse_xml,
        _scan_special_screen,
    )
    from .post_extractor import _compute_post_id_from_nodes
    from .feed_pipeline import _extract_header_stats

    t0 = time.monotonic()

    def _diag(reason: str, **extra) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "reason_code": reason,
            "posts_returned": 0,
            "comments_returned": 0,
            "anchor_button_found": False,
            "nodes_in_band": 0,
            "candidate_clusters": 0,
            "locale_tokens_hit": [],
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
        }
        base.update(extra)
        return base

    root = _parse_xml(xml)
    if root is None:
        return [], _diag("xml_parse_error")

    special = _scan_special_screen(root)
    if special:
        return [], _diag(special)

    if not _hierarchy_is_fb_comment_sheet(root):
        return [], _diag(
            "not_comment_sheet",
            anchor_button_found=False,
            nodes_in_band=0,
        )

    all_nodes = _collect_text_nodes(root, toolbar_cutoff_y=200)
    if not all_nodes:
        return [], _diag("no_text_nodes")

    row_match_pid = parent_post_id
    if parent_post_id is None:
        parent_post_id = _compute_post_id_from_nodes(all_nodes)

    action_btn_y2, _action_btn_y_mid, comment_y_max = _resolve_comment_region_anchors(root, row_match_pid)
    anchor_found = action_btn_y2 is not None
    screen_w, screen_h = _infer_screen_size(root)
    comment_x_max = max(380, int(screen_w * 0.64))

    def _in_comment_vertical_band(n: Dict[str, Any]) -> bool:
        x0 = n["bounds"][0]
        if x0 >= comment_x_max:
            if x0 < screen_w - 24 and _is_comment_reaction_count_row(n["text"]):
                pass
            else:
                return False
        if action_btn_y2 is not None and n["cy"] <= action_btn_y2:
            return False
        if comment_y_max is not None and n["bounds"][1] >= comment_y_max:
            return False
        return True

    comment_nodes: List[Dict[str, Any]] = []
    for n in all_nodes:
        if not _in_comment_vertical_band(n):
            continue
        if _is_compact_comment_action_label(n["text"], list(n["bounds"])):
            continue
        if n.get("is_author_hint") and not _is_comment_left_avatar_name_strip(n):
            continue
        if n["bounds"][0] >= 150:
            comment_nodes.append(n)
        elif _is_comment_left_avatar_name_strip(n):
            comment_nodes.append(n)

    if not comment_nodes:
        reason = "anchor_not_found" if not anchor_found else "no_nodes_in_band"
        return [], _diag(
            reason,
            anchor_button_found=anchor_found,
            nodes_in_band=0,
            screen_size=[screen_w, screen_h],
        )

    comment_nodes.sort(key=lambda n: (n["bounds"][1] // 35, n["bounds"][0]))

    clusters = _cluster_into_comments(comment_nodes)
    result: List[Dict[str, Any]] = []
    last_kept_body: Optional[Dict[str, Any]] = None
    for cluster in clusters:
        if len(result) >= max_items:
            break
        cluster_min_x = min((n["bounds"][0] for n in cluster if n["bounds"]), default=150)
        comment = _extract_comment(cluster, parent_post_id, cluster_min_x=cluster_min_x)
        if not comment or _is_comment_row_parse_noise(comment) or _is_junk_parsed_comment_row(comment):
            continue
        if _is_duplicate_short_author_footer_row(comment, last_kept_body):
            continue
        result.append(comment)
        last_kept_body = comment

    header_stats = _extract_header_stats(root, y_max=action_btn_y2)
    if header_stats:
        result.insert(0, header_stats)

    _pr = header_stats.get("reactions") if header_stats else None
    _ps = header_stats.get("shares") if header_stats else None
    _pc = header_stats.get("comments") if header_stats else None
    if _pr is not None or _ps is not None or _pc is not None:
        for c in result:
            if c.get("_type") == "post_stats":
                continue
            if _pr is not None:
                c["post_reactions"] = _pr
            if _ps is not None:
                c["post_shares"] = _ps
            if _pc is not None:
                c["post_comments"] = _pc

    if not result:
        return [], _diag(
            "empty_cluster",
            anchor_button_found=anchor_found,
            nodes_in_band=len(comment_nodes),
            candidate_clusters=len(clusters),
            screen_size=[screen_w, screen_h],
        )

    return result, {
        "reason_code": "ok",
        "comments_returned": len([c for c in result if c.get("_type") != "post_stats"]),
        "anchor_button_found": anchor_found,
        "nodes_in_band": len(comment_nodes),
        "candidate_clusters": len(clusters),
        "screen_size": [screen_w, screen_h],
        "locale_tokens_hit": [],
        "has_header_stats": bool(header_stats),
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
    }


def parse_fb_comments_from_xml(
    xml: str,
    parent_post_id: Optional[str] = None,
    max_items: int = 50,
) -> List[Dict[str, Any]]:
    rows, _ = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id, max_items)
    return rows


__all__ = [
    "_find_binh_luan_button_in_element",
    "_legacy_last_binh_luan_anchors",
    "_resolve_comment_region_anchors",
    "_find_binh_luan_button_bounds_in_element",
    "resolve_topmost_comment_target_from_xml",
    "parse_fb_comments_from_xml_with_diagnostic",
    "parse_fb_comments_from_xml",
    "_post_id_from_ctx",
]

