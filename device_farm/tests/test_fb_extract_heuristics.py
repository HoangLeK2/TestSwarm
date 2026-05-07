"""Focused unit tests: comment merge/extract, badges, long-post cluster, link/reshare heuristics."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from tasks.fb_extract import (
    _cluster_into_comments,
    _cluster_into_posts,
    _comment_line_is_badge,
    _is_comment_row_parse_noise,
    _hierarchy_is_fb_comment_sheet,
    _extract_comment,
    _extract_post,
    parse_fb_posts_from_xml,
    _is_cmt_noise,
    _is_junk_parsed_comment_row,
    _looks_like_comment_timestamp_row,
    _merge_post_type,
    _RE_POST_RESHARE_HEADER,
    _refine_comment_author_from_cluster,
    _should_merge_post_nodes_despite_vertical_gap,
    _should_merge_split_comment_nodes,
)


def _pn(
    text: str,
    cy: int,
    *,
    x0: int = 40,
    w: int = 900,
    is_author_hint: bool = False,
) -> Dict[str, Any]:
    y1, y2 = cy - 18, cy + 18
    return {
        "text": text,
        "bounds": (x0, y1, x0 + w, y2),
        "cy": cy,
        "resource_id": "",
        "is_author_hint": is_author_hint,
    }


# ── merge_post_type ──────────────────────────────────────────────────────────


def test_parse_posts_entrypoint_delegates_to_refactored_clusterer(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Dict[str, Any]] = []

    def fake_cluster(nodes: List[Dict[str, Any]], *, screen_height: int = 2200) -> List[List[Dict[str, Any]]]:
        calls.append({"nodes": nodes, "screen_height": screen_height})
        return []

    monkeypatch.setattr("tasks.fb_extract.clustering._cluster_into_posts", fake_cluster)

    xml = """
    <hierarchy rotation="0">
      <node class="android.widget.TextView" text="Author" bounds="[20,300][220,340]" />
      <node class="android.widget.TextView" text="Body" bounds="[20,360][420,420]" />
    </hierarchy>
    """

    assert parse_fb_posts_from_xml(xml) == []
    assert len(calls) == 1
    assert [node["text"] for node in calls[0]["nodes"]] == ["Author", "Body"]


def test_merge_post_type_short_body_plus_permalink_is_link() -> None:
    assert _merge_post_type("text", None, None, has_fb_link=True, body_len=12) == "link"
    assert _merge_post_type("text", None, None, has_fb_link=True, body_len=55) == "link"


def test_merge_post_type_long_body_stays_text_even_with_permalink() -> None:
    assert _merge_post_type("text", None, None, has_fb_link=True, body_len=56) == "text"
    assert _merge_post_type("text", None, None, has_fb_link=True, body_len=200) == "text"


def test_merge_post_type_no_permalink_never_promotes_to_link() -> None:
    assert _merge_post_type("text", None, None, has_fb_link=False, body_len=5) == "text"


def test_merge_post_type_reel_wins_over_link_hint() -> None:
    assert _merge_post_type("link", None, "reel", has_fb_link=True, body_len=10) == "reel"
    assert _merge_post_type("text", "reel", None, has_fb_link=True, body_len=10) == "reel"


def test_merge_post_type_structural_video_keeps_video_not_reel_rid() -> None:
    assert _merge_post_type("text", "video", "video", has_fb_link=False, body_len=80) == "video"


# ── post vertical merge despite gap ───────────────────────────────────────────


def test_should_merge_post_nodes_despite_gap_true_same_margin_long_chunks() -> None:
    prev = _pn("P" * 36 + " first paragraph of post body here.", 100)
    nxt = _pn("Q" * 36 + " second paragraph still same post.", 320)
    gap = 320 - 100
    thr = max(120, min(290, int(2200 * 0.076)))
    assert gap > thr
    assert _should_merge_post_nodes_despite_vertical_gap(prev, nxt, gap, thr) is True


def test_should_merge_post_nodes_false_when_x_misaligned() -> None:
    prev = _pn("P" * 40 + " aligned left margin forty chars.", 100, x0=40)
    nxt = _pn("Q" * 40 + " shifted too far right for same post.", 300, x0=140)
    gap = 200
    thr = 167
    assert _should_merge_post_nodes_despite_vertical_gap(prev, nxt, gap, thr) is False


def test_should_merge_post_nodes_false_when_gap_exceeds_relax_cap() -> None:
    prev = _pn("P" * 40 + " paragraph one here.", 100)
    nxt = _pn("Q" * 40 + " paragraph two far below.", 620)
    gap = 520
    thr = 167
    max_relax = min(540, int(thr * 2.4))
    assert gap > max_relax
    assert _should_merge_post_nodes_despite_vertical_gap(prev, nxt, gap, thr) is False


def test_should_merge_post_nodes_false_second_line_short_single_token() -> None:
    prev = _pn("P" * 40 + " long first chunk.", 100)
    nxt = _pn("Shortname", 280, x0=42)
    gap = 180
    thr = 167
    assert _should_merge_post_nodes_despite_vertical_gap(prev, nxt, gap, thr) is False


def test_should_merge_post_nodes_false_chunk_too_short() -> None:
    prev = _pn("short", 100)
    nxt = _pn("also too short for merge rule", 250)
    assert _should_merge_post_nodes_despite_vertical_gap(prev, nxt, 150, 120) is False


# ── reshare / link regex ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "snippet",
    [
        "Đã chia sẻ một liên kết",
        "đã chia sẻ bài viết hay",
        "shared a link",
        "Shared by Someone",
        "reposted yesterday",
        "đăng lại bài này",
        "bài viết gốc",
        "bài đăng gốc",
    ],
)
def test_re_post_reshare_header_matches_vn_en(snippet: str) -> None:
    assert _RE_POST_RESHARE_HEADER.search(snippet)


# ── comment badge detection ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label",
    [
        "Quan tâm",
        "TOP FAN",
        "fan cuồng",
        "Người hay tương tác",
        "chuyên gia được xác minh",
        "visual storyteller",
    ],
)
def test_comment_line_is_badge_positive(label: str) -> None:
    assert _comment_line_is_badge(label) is True


def test_comment_line_is_badge_rejects_long_random_text() -> None:
    assert _comment_line_is_badge("a" * 80) is False
    assert _comment_line_is_badge("") is False


# ── comment timestamp row (feed bleed) ────────────────────────────────────────


def test_looks_like_comment_timestamp_row_chia_se() -> None:
    assert _looks_like_comment_timestamp_row("1 ngày•Chia sẻ với: Công khai") is True


# ── split-comment merge gates ────────────────────────────────────────────────


def _cn(text: str, cy: int, x0: int = 200) -> Dict[str, Any]:
    return _pn(text, cy, x0=x0, w=400)


def test_should_merge_split_name_then_badge() -> None:
    prev, nxt = _cn("Minh", 100), _cn("Quan tâm", 190)
    assert _should_merge_split_comment_nodes(prev, nxt, 90) is True


def test_should_merge_split_badge_then_body() -> None:
    prev, nxt = _cn("Top fan", 100), _cn("This is the actual comment body here.", 200)
    assert _should_merge_split_comment_nodes(prev, nxt, 100) is True


def test_should_merge_split_two_body_paragraphs() -> None:
    prev = _cn("First paragraph of comment with enough chars.", 100)
    nxt = _cn("Second paragraph still same comment.", 220)
    assert _should_merge_split_comment_nodes(prev, nxt, 120) is True


def test_should_merge_split_false_gap_too_large() -> None:
    prev, nxt = _cn("Alice", 100), _cn("Body text far away", 900)
    assert _should_merge_split_comment_nodes(prev, nxt, 800) is False


def test_should_merge_split_false_timestamp_row() -> None:
    prev = _cn("Alice", 100)
    nxt = _cn("2 giờ•Chia sẻ với: Công khai", 200)
    assert _should_merge_split_comment_nodes(prev, nxt, 100) is False


# ── cluster_into_comments integration ────────────────────────────────────────


def test_cluster_into_comments_merges_vertical_name_body_then_splits_on_like() -> None:
    nodes: List[Dict[str, Any]] = [
        _cn("Alice", 100),
        _cn("Đây là nội dung bình luận đủ dài.", 220),
        _cn("Nút Thích bình luận của Alice.", 340),
        _cn("Bob", 460),
        _cn("Phản hồi khác cũng đủ dài.", 580),
        _cn("Nút Thích bình luận của Bob.", 700),
    ]
    clusters = _cluster_into_comments(nodes)
    assert len(clusters) == 2
    assert any("Alice" in n["text"] for n in clusters[0])
    assert any("Nút Thích" in n["text"] for n in clusters[0])
    assert any(n["text"] == "Bob" for n in clusters[1])


# ── extract_comment variants ──────────────────────────────────────────────────


def test_extract_comment_middle_dot_name_badge() -> None:
    cluster = [
        {"text": "Hùng · Siêu fan", "bounds": (200, 0, 500, 40)},
        {"text": "Nội dung sau danh hiệu.", "bounds": (200, 50, 500, 90)},
    ]
    c = _extract_comment(cluster, parent_post_id="p", cluster_min_x=200)
    assert c is not None
    assert c["author"] == "Hùng"
    assert c.get("badges") and any("siêu fan" in b.lower() for b in c["badges"])


def test_extract_comment_name_dot_relative_time() -> None:
    cluster = [
        {"text": "Lan · 5 giờ", "bounds": (200, 0, 400, 40)},
        {"text": "Câu trả lời có đủ chữ.", "bounds": (200, 50, 500, 90)},
    ]
    c = _extract_comment(cluster, parent_post_id="p", cluster_min_x=200)
    assert c is not None
    assert c["author"] == "Lan"
    assert c.get("timestamp") and "5" in c["timestamp"]


def test_extract_comment_indent_level_nested() -> None:
    cluster = [
        {"text": "Z", "bounds": (290, 0, 320, 30)},
        {"text": "Nested reply body long enough here.", "bounds": (290, 40, 500, 80)},
    ]
    c = _extract_comment(cluster, parent_post_id="p", cluster_min_x=290)
    assert c is not None
    assert c["indent_level"] == 2


# ── refine author ─────────────────────────────────────────────────────────────


def test_refine_author_keeps_when_like_prefix_not_extension() -> None:
    cluster = [
        {"text": "Maria", "bounds": (200, 0, 300, 40)},
        {"text": "Nút Thích bình luận của Van.", "bounds": (200, 50, 500, 90)},
    ]
    assert _refine_comment_author_from_cluster(cluster, "Maria") == "Maria"


def test_refine_author_upgrades_when_full_name_prefix_match() -> None:
    cluster = [
        {"text": "Nút Thích bình luận của Nguyễn Văn An.", "bounds": (200, 0, 500, 40)},
    ]
    assert _refine_comment_author_from_cluster(cluster, "Nguyễn") == "Nguyễn Văn An"


# ── cmt noise / junk rows ────────────────────────────────────────────────────


def test_is_cmt_noise_write_comment_en() -> None:
    assert _is_cmt_noise("Write a public comment…") is True
    assert _is_cmt_noise("Add a comment") is True


def test_is_junk_parsed_row_composer_as_author() -> None:
    assert _is_junk_parsed_comment_row({"author": "Viết bình luận...", "text": ""}) is True
    assert _is_junk_parsed_comment_row({"author": "x", "text": "Write a comment here"}) is True


def test_parse_noise_vs_storage_empty_multitoken_author() -> None:
    """Parse giữ hàng ghost để corpus; lưu DB / ctx scenario bỏ (cần body)."""
    c = {"author": "Van Nguyen", "text": ""}
    assert _is_comment_row_parse_noise(c) is False
    assert _is_junk_parsed_comment_row(c) is True


def test_parse_noise_drops_timestamp_leak_in_comment_body() -> None:
    c = {"author": "", "text": "27 thg 2•Chia sẻ với: Công khai"}
    assert _is_comment_row_parse_noise(c) is True
    assert _is_junk_parsed_comment_row(c) is True


def test_parse_noise_drops_badge_duplicate_author_body() -> None:
    c = {"author": "Người đóng góp nổi bật", "text": "Người đóng góp nổi bật"}
    assert _is_comment_row_parse_noise(c) is True


def test_comment_sheet_detects_text_close_plus_composer_footer() -> None:
    from lxml import etree

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node package="com.facebook.katana" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node package="com.facebook.katana" class="android.widget.Button" text="Đóng" bounds="[40,120][180,180]"/>
    <node package="com.facebook.katana" class="android.widget.Button" text="Đang hiển thị Phù hợp nhất bình luận" bounds="[300,640][980,710]"/>
    <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,720][1080,2130]">
      <node package="com.facebook.katana" class="android.view.ViewGroup" bounds="[0,760][1080,980]">
        <node package="com.facebook.katana" class="android.widget.TextView" text="Nguyen Van A" bounds="[210,790][470,835]"/>
        <node package="com.facebook.katana" class="android.widget.TextView" text="Comment body here" bounds="[210,845][860,910]"/>
      </node>
    </node>
    <node package="com.facebook.katana" class="android.widget.AutoCompleteTextView" text="Viết bình luận..." bounds="[120,2170][980,2260]"/>
  </node>
</hierarchy>"""
    root = etree.fromstring(xml.encode("utf-8"))
    assert _hierarchy_is_fb_comment_sheet(root) is True


def test_comment_sheet_does_not_misclassify_feed_with_close_and_inline_comment_ui() -> None:
    from lxml import etree

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node package="com.facebook.katana" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node package="com.facebook.katana" class="android.widget.Button" text="Đóng" bounds="[40,120][180,180]"/>
    <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,200][1080,2360]">
      <node package="com.facebook.katana" class="android.view.ViewGroup" bounds="[0,280][1080,1180]">
        <node package="com.facebook.katana" class="android.widget.TextView" text="Tac Gia" bounds="[40,320][280,365]"/>
        <node package="com.facebook.katana" class="android.widget.TextView" text="Noi dung bai viet rat dai de parse feed" bounds="[40,410][980,520]"/>
        <node package="com.facebook.katana" class="android.widget.Button" text="Đang hiển thị Phù hợp nhất bình luận" bounds="[320,890][980,960]"/>
        <node package="com.facebook.katana" class="android.widget.AutoCompleteTextView" text="Viết bình luận..." bounds="[120,980][980,1060]"/>
      </node>
    </node>
  </node>
</hierarchy>"""
    root = etree.fromstring(xml.encode("utf-8"))
    assert _hierarchy_is_fb_comment_sheet(root) is False


# ── extract_post link classification ─────────────────────────────────────────


def test_extract_post_m_me_in_body_is_link_type() -> None:
    cluster = [
        _pn("PageName", 120, x0=34, is_author_hint=True),
        _pn("Xem thêm tại https://m.me/shopname nhé mọi người.", 220),
    ]
    p = _extract_post(cluster, 0)
    assert p is not None
    assert p["post_type"] == "link"


def test_extract_post_short_text_plus_stable_fb_id_becomes_link() -> None:
    cluster = [
        _pn("Author", 100, x0=34, is_author_hint=True),
        _pn("Ngắn.", 200),
    ]
    p = _extract_post(cluster, 0, fb_post_id="123456789", permalink_candidates=["https://facebook.com/x"])
    assert p is not None
    assert p["post_type"] == "link"


def test_extract_post_reshare_header_plus_permalink_link() -> None:
    cluster = [
        _pn("User", 100, x0=34, is_author_hint=True),
        _pn("Đã chia sẻ một liên kết", 160),
        _pn("Headline only", 220),
        _pn("1 giờ", 300),
    ]
    p = _extract_post(
        cluster,
        0,
        fb_post_id="999",
        permalink_candidates=[],
    )
    assert p is not None
    assert p["post_type"] == "link"


def test_extract_post_single_long_body_node_without_timestamp_anchor() -> None:
    """Full post text in one node, no time row → anchor_idx=len; i=0 must still become body."""
    long_body = "Lựa chọn OpenClaw hay Manus để xây dựng hệ thống AI Agent\n\n" + "x" * 400
    cluster = [_pn(long_body, 1500, x0=42, w=1100)]
    p = _extract_post(cluster, 0)
    assert p is not None
    assert "OpenClaw" in (p["text"] or "")
    assert len(p["text"] or "") > 300


def test_parse_fb_posts_from_xml_long_body_capture_213524() -> None:
    cap = (
        Path(__file__).resolve().parent.parent
        / "captures"
        / "49c62ff79ec0c35d_2026-04-12_213524"
        / "step_000_extract_pre_hierarchy.xml"
    )
    if not cap.is_file():
        pytest.skip("capture xml not present")
    posts = parse_fb_posts_from_xml(cap.read_text(encoding="utf-8"), 0)
    assert posts
    assert any(len((p.get("text") or "")) > 800 for p in posts), posts


# ── cluster_into_posts does not merge distinct timestamps ───────────────────


def test_cluster_into_posts_splits_on_second_timestamp_gap() -> None:
    nodes = [
        _pn("Author One", 100),
        _pn("Body one enough length here " + "x" * 20, 180),
        _pn("2 giờ", 260),
        _pn("Author Two", 520),
        _pn("Different post body " + "y" * 24, 600),
        _pn("5 giờ", 680),
    ]
    clusters = _cluster_into_posts(nodes, screen_height=2200)
    assert len(clusters) >= 2
