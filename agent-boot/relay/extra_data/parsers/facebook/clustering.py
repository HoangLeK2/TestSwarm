from __future__ import annotations

from typing import Dict, List

from .constants import (
    _MAX_TS_ANCHOR_NODE_LEN,
    _NOISE_PREFIXES,
    _RE_CMT_LIKE_BTN,
    _RE_CMT_REPLY_BTN,
    _RE_TS,
)
from .filters import (
    _comment_line_is_badge,
    _is_cmt_noise,
    _is_comment_image_placeholder_text,
    _is_comment_reaction_count_row,
    _looks_like_comment_timestamp_row,
)


# Responsibility: nodes -> clusters (feed posts + comment bodies) and
# merge/split heuristics.

def _should_merge_post_nodes_despite_vertical_gap(
    prev: Dict[str, Any],
    nxt: Dict[str, Any],
    gap: float,
    gap_threshold: float,
) -> bool:
    """Hai node text dài cùng lề — hay là hai đoạn một bài bị tách dọc."""
    if gap <= gap_threshold:
        return False
    max_relax = min(540, int(gap_threshold * 2.4))
    if gap > max_relax:
        return False
    pt = prev["text"].strip()
    nt = nxt["text"].strip()
    tl = nt.lower()
    if len(pt) < 32 or len(nt) < 24:
        return False
    # Dòng tên ngắn (một token) — thường là đầu bài kế, không gộp
    if len(nt) <= 26 and " " not in nt and "http" not in tl:
        return False
    # Hàng giờ tương đối ngắn — ranh giới bài / stats
    if len(nt) <= 44 and _RE_TS.search(nt) and "http" not in tl:
        return False
    px, nx = prev["bounds"][0], nxt["bounds"][0]
    if abs(px - nx) > 52:
        return False
    plow = pt.lower()
    if any(plow.startswith(p) for p in _NOISE_PREFIXES):
        return False
    return True


def _cluster_into_posts(
    nodes: List[Dict[str, Any]],
    *,
    screen_height: int = 2200,
) -> List[List[Dict[str, Any]]]:
    if not nodes:
        return []
    # Scale with viewport; clamp — tăng nhẹ để ít tách đoạn body dài.
    gap_threshold = max(120, min(290, int(screen_height * 0.076)))
    ts_gap_split = max(18, gap_threshold // 5)
    clusters: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = [nodes[0]]
    prev_cy = nodes[0]["cy"]
    current_has_ts = bool(_RE_TS.search(nodes[0]["text"]))

    for node in nodes[1:]:
        gap = node["cy"] - prev_cy
        is_ts = bool(_RE_TS.search(node["text"]))
        prev_node = current[-1]
        merge_despite_gap = gap > gap_threshold and _should_merge_post_nodes_despite_vertical_gap(
            prev_node,
            node,
            gap,
            gap_threshold,
        )
        if merge_despite_gap:
            current.append(node)
            if is_ts:
                current_has_ts = True
            prev_cy = node["cy"]
            continue

        if gap > gap_threshold or (current_has_ts and is_ts and gap > ts_gap_split):
            clusters.append(current)
            current = [node]
            current_has_ts = is_ts
        else:
            current.append(node)
            if is_ts:
                current_has_ts = True
        prev_cy = node["cy"]

    if current:
        clusters.append(current)
    return clusters


def _should_merge_split_comment_nodes(
    prev: Dict[str, Any],
    nxt: Dict[str, Any],
    gap: float,
) -> bool:
    """Gộp hai node liên tiếp bị FB tách theo chiều dọc (name/badge/body)."""
    pt = prev["text"].strip()
    nt = nxt["text"].strip()
    if not pt or not nt:
        return False
    pl, nl = len(pt), len(nt)
    px, nx = prev["bounds"][0], nxt["bounds"][0]

    # Large vertical gap: image-only tile (a11y text "Ảnh") dưới badge/name.
    if _comment_line_is_badge(pt) and _is_comment_image_placeholder_text(nt) and gap <= 1400:
        return True
    if 2 <= pl <= 100 and not _comment_line_is_badge(pt) and _is_comment_image_placeholder_text(nt) and gap < 1400:
        return True

    # Image tile then footer rows (timestamp / like) — vẫn là cùng comment.
    if _is_comment_image_placeholder_text(pt) and gap < 900:
        if len(nt) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(nt):
            return True
        if _looks_like_comment_timestamp_row(nt):
            return True
        if _RE_CMT_LIKE_BTN.match(nt) or _RE_CMT_REPLY_BTN.match(nt):
            return True

    if gap <= 80 or gap > 720:
        return False
    if abs(px - nx) > 120:
        # Name (x<150) + badge row trong main column lệch lớn → không gộp.
        if not (
            2 <= pl <= 100
            and not _comment_line_is_badge(pt)
            and _comment_line_is_badge(nt)
            and int(prev["bounds"][0]) < 150
        ):
            return False

    if _looks_like_comment_timestamp_row(pt) or _looks_like_comment_timestamp_row(nt):
        return False
    if _RE_CMT_LIKE_BTN.match(nt) or _RE_CMT_REPLY_BTN.match(nt):
        return False
    if _is_cmt_noise(nt):
        return False

    plow = pt.lower()
    if "http" in plow or "www." in plow:
        return False
    if plow.startswith("nút ") or plow.startswith("trả lời"):
        return False

    # Tên ngắn + badge (chip dưới tên)
    if 2 <= pl <= 100 and _comment_line_is_badge(nt):
        return True
    # Tên / avatar label + badge phía dưới (FB tách dọc)
    if 2 <= pl <= 100 and not _comment_line_is_badge(pt) and _comment_line_is_badge(nt) and gap < 420:
        return True
    # Badge + body (VN/EN UI)
    if _comment_line_is_badge(pt) and nl >= 12 and not _comment_line_is_badge(nt):
        return True
    # Tên + body
    if 2 <= pl <= 100:
        if "•" in pt and pl > 40 and "chia sẻ" not in plow:
            return False
        min_nl = 12 if (" " in nt or nl >= 18) else 22
        if nl >= min_nl:
            if nl < 30 and " " not in nt:
                return False
            return True

    # Hai khối body dài liền nhau (FB tách ViewGroup)
    if pl >= 28 and nl >= 28 and gap <= 300:
        if _RE_CMT_LIKE_BTN.match(pt) or _RE_CMT_REPLY_BTN.match(pt):
            return False
        if " " not in nt and nl < 45:
            return False
        return True

    return False


def _cluster_into_comments(
    nodes: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """Cluster comment text-nodes into per-comment groups."""
    if not nodes:
        return []
    gap = 80
    clusters: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = [nodes[0]]
    prev_cy = nodes[0]["cy"]
    pending_footer = False

    def _inline_comment_footer_row(text: str, footer_gap: float) -> bool:
        tt = text.strip()
        if footer_gap >= 200:
            return False
        if _RE_CMT_REPLY_BTN.match(tt):
            return True
        if _is_comment_reaction_count_row(tt):
            return True
        if len(tt) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(tt):
            return True
        return False

    for node in nodes[1:]:
        node_gap = node["cy"] - prev_cy
        t = node["text"].strip()
        is_end_marker = bool(_RE_CMT_LIKE_BTN.match(t))

        if pending_footer:
            if _inline_comment_footer_row(t, node_gap):
                current.append(node)
                prev_cy = node["cy"]
                continue
            clusters.append(current)
            current = [node]
            prev_cy = node["cy"]
            pending_footer = False
            continue

        merge_name_body = (
            not is_end_marker
            and node_gap > gap
            and bool(current)
            and _should_merge_split_comment_nodes(current[-1], node, node_gap)
        )
        if merge_name_body:
            current.append(node)
            prev_cy = node["cy"]
            continue

        if node_gap > gap or is_end_marker:
            if is_end_marker:
                current.append(node)
                pending_footer = True
                prev_cy = node["cy"]
                continue
            if current:
                clusters.append(current)
            current = [node]
        else:
            current.append(node)

        prev_cy = node["cy"]

    if current:
        clusters.append(current)
    return clusters


def _coalesce_comment_clusters(
    clusters: List[List[Dict[str, Any]]],
) -> List[List[Dict[str, Any]]]:
    """Merge split name-only + body-only clusters (common on FB comment sheet dumps)."""
    from .comment_pipeline import _extract_comment

    if len(clusters) < 2:
        return clusters

    def _row(cluster: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if not cluster:
            return None
        min_x = min((n["bounds"][0] for n in cluster if n.get("bounds")), default=150)
        return _extract_comment(cluster, None, cluster_min_x=min_x)

    merged: List[List[Dict[str, Any]]] = []
    i = 0
    while i < len(clusters):
        cur = clusters[i]
        if i + 1 < len(clusters):
            row = _row(cur)
            nxt_row = _row(clusters[i + 1])
            if row and nxt_row:
                author = (row.get("author") or "").strip()
                text = (row.get("text") or "").strip()
                n_author = (nxt_row.get("author") or "").strip()
                n_text = (nxt_row.get("text") or "").strip()
                if author and not text and n_text:
                    merged.append(cur + clusters[i + 1])
                    i += 2
                    continue
        merged.append(cur)
        i += 1
    return merged


__all__ = [
    "_cluster_into_posts",
    "_cluster_into_comments",
    "_coalesce_comment_clusters",
    "_should_merge_post_nodes_despite_vertical_gap",
    "_should_merge_split_comment_nodes",
]

