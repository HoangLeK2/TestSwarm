from __future__ import annotations

"""
tests/test_fb_group_crawl.py — Unit tests for tasks/fb_group_crawl.py XML parsing pipeline.

All tests are pure (no device needed).

Run: pytest tests/test_fb_group_crawl.py -v
"""

import re
from typing import Any, Dict, List

import pytest
from lxml import etree as _lxml

from tasks.fb_group_crawl import (
    _RE_TS,
    _cluster_into_posts,
    _collect_text_nodes,
    _dedup,
    _extract_post,
    _extract_posts_from_recycler,
    _is_noise_text,
    _parse_bounds,
    parse_fb_posts_from_xml,
)


# ── XML building helpers ───────────────────────────────────────────────────────


def _node(
    text: str = "",
    content_desc: str = "",
    resource_id: str = "",
    bounds: str = "[0,300][500,350]",
    cls: str = "android.widget.TextView",
    scrollable: str = "false",
    clickable: str = "false",
    **extra,
) -> _lxml.Element:
    """Create a minimal lxml <node> element."""
    el = _lxml.Element("node")
    el.set("class", cls)
    el.set("text", text)
    el.set("content-desc", content_desc)
    el.set("resource-id", resource_id)
    el.set("bounds", bounds)
    el.set("scrollable", scrollable)
    el.set("clickable", clickable)
    for k, v in extra.items():
        el.set(k, v)
    return el


def _recycler_xml(post_children_xml: str) -> str:
    """Wrap post XML inside a scrollable RecyclerView hierarchy."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hierarchy rotation="0">'
        '<node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">'
        '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" '
        'bounds="[0,200][1080,1920]">'
        + post_children_xml
        + "</node>"
        "</node>"
        "</hierarchy>"
    )


def _webview_xml(content_nodes_xml: str) -> str:
    """Wrap content inside a WebView (triggers Strategy B fallback)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hierarchy rotation="0">'
        '<node class="android.webkit.WebView" bounds="[0,0][1080,1920]">'
        + content_nodes_xml
        + "</node>"
        "</hierarchy>"
    )


# ── Single-post XML fragment helpers ──────────────────────────────────────────

_POST_A = (
    '<node class="android.view.ViewGroup" bounds="[0,300][1080,900]">'
    '<node class="android.widget.TextView" text="Nguyen Van A" bounds="[0,310][500,360]"/>'
    '<node class="android.widget.TextView" text="2 giờ trước" bounds="[0,365][300,390]"/>'
    '<node class="android.widget.TextView" text="Hôm nay thời tiết đẹp quá" bounds="[0,400][1080,450]"/>'
    '<node class="android.widget.TextView" text="1.2K" bounds="[0,600][150,630]"/>'
    '<node class="android.widget.TextView" text="45 bình luận" bounds="[160,600][350,630]"/>'
    '<node class="android.widget.TextView" text="12 lượt chia sẻ" bounds="[360,600][550,630]"/>'
    "</node>"
)

_POST_B = (
    '<node class="android.view.ViewGroup" bounds="[0,950][1080,1500]">'
    '<node class="android.widget.TextView" text="Tran Thi B" bounds="[0,960][500,1010]"/>'
    '<node class="android.widget.TextView" text="3 giờ trước" bounds="[0,1015][300,1040]"/>'
    '<node class="android.widget.TextView" text="Chia sẻ kinh nghiệm du lịch" bounds="[0,1050][1080,1100]"/>'
    "</node>"
)


# ── Strategy A: RecyclerView ───────────────────────────────────────────────────


def test_strategy_a_returns_two_posts():
    """RecyclerView with 2 direct post children → 2 posts returned."""
    xml = _recycler_xml(_POST_A + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    assert len(posts) == 2


def test_strategy_a_post_author():
    xml = _recycler_xml(_POST_A + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    authors = {p["author"] for p in posts}
    assert "Nguyen Van A" in authors


def test_strategy_a_post_timestamp():
    xml = _recycler_xml(_POST_A + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    timestamps = {p["timestamp"] for p in posts}
    assert "2 giờ trước" in timestamps


# ── Strategy B: WebView fallback gap clustering ────────────────────────────────


def test_strategy_b_webview_returns_posts():
    """No RecyclerView → gap clustering fallback should still return posts."""
    # Two text blocks separated by a large vertical gap
    content = (
        '<node class="android.widget.TextView" text="Le Van C" bounds="[0,300][500,350]"/>'
        '<node class="android.widget.TextView" text="1 ngày trước" bounds="[0,355][300,380]"/>'
        '<node class="android.widget.TextView" text="Bài viết hay" bounds="[0,385][1080,430]"/>'
        # large gap — new post starts here (y > 430+160)
        '<node class="android.widget.TextView" text="Pham Thi D" bounds="[0,700][500,750]"/>'
        '<node class="android.widget.TextView" text="5 giờ trước" bounds="[0,755][300,780]"/>'
        '<node class="android.widget.TextView" text="Nội dung bài mới" bounds="[0,785][1080,830]"/>'
    )
    xml = _webview_xml(content)
    posts = parse_fb_posts_from_xml(xml, source_index=1)
    assert len(posts) >= 1
    assert any(p["author"] == "Le Van C" for p in posts)


# ── Post field extraction ──────────────────────────────────────────────────────


def test_post_field_reactions_comments_shares():
    xml = _recycler_xml(_POST_A + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    post_a = next(p for p in posts if p["author"] == "Nguyen Van A")
    assert post_a["reactions"] == "1.2K"
    assert post_a["comments"] == "45"
    assert post_a["shares"] == "12"


def test_post_body_text():
    xml = _recycler_xml(_POST_A + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    post_a = next(p for p in posts if p["author"] == "Nguyen Van A")
    assert "Hôm nay thời tiết đẹp quá" in post_a["text"]


# ── post_type = photo ─────────────────────────────────────────────────────────


def test_post_type_photo():
    """Cluster with content-desc starting with 'Ảnh' → post_type='photo'."""
    post_photo_xml = (
        '<node class="android.view.ViewGroup" bounds="[0,300][1080,900]">'
        '<node class="android.widget.TextView" text="Author Photo" bounds="[0,310][500,360]"/>'
        '<node class="android.widget.TextView" text="1 giờ trước" bounds="[0,365][300,390]"/>'
        '<node class="android.widget.TextView" text="Đây là bài viết có ảnh" bounds="[0,400][1080,450]"/>'
        '<node class="android.widget.ImageView" content-desc="Ảnh của Author Photo tại bãi biển" bounds="[0,460][1080,750]"/>'
        "</node>"
    )
    xml = _recycler_xml(post_photo_xml + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    photo_posts = [p for p in posts if p["post_type"] == "photo"]
    assert len(photo_posts) == 1
    assert photo_posts[0]["image_desc"] is not None
    assert "Ảnh" in photo_posts[0]["image_desc"]


# ── post_type = video ─────────────────────────────────────────────────────────


def test_post_type_video():
    """Cluster text contains 'video' → post_type='video'."""
    post_xml = (
        '<node class="android.view.ViewGroup" bounds="[0,300][1080,900]">'
        '<node class="android.widget.TextView" text="Video Author" bounds="[0,310][500,360]"/>'
        '<node class="android.widget.TextView" text="30 phút trước" bounds="[0,365][300,390]"/>'
        '<node class="android.widget.TextView" text="Xem video này đi mọi người" bounds="[0,400][1080,450]"/>'
        "</node>"
    )
    xml = _recycler_xml(post_xml + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    video_posts = [p for p in posts if p["post_type"] == "video"]
    assert len(video_posts) == 1


# ── post_type = reel ──────────────────────────────────────────────────────────


def test_post_type_reel():
    """Cluster text contains 'Reels' → post_type='reel'."""
    post_xml = (
        '<node class="android.view.ViewGroup" bounds="[0,300][1080,900]">'
        '<node class="android.widget.TextView" text="Reel Author" bounds="[0,310][500,360]"/>'
        '<node class="android.widget.TextView" text="2 giờ trước" bounds="[0,365][300,390]"/>'
        '<node class="android.widget.TextView" text="Xem Reels của tôi nhé" bounds="[0,400][1080,450]"/>'
        "</node>"
    )
    xml = _recycler_xml(post_xml + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    reel_posts = [p for p in posts if p["post_type"] == "reel"]
    assert len(reel_posts) == 1


# ── post_type = link ──────────────────────────────────────────────────────────


def test_post_type_link():
    """Cluster text contains 'https://...' → post_type='link'."""
    post_xml = (
        '<node class="android.view.ViewGroup" bounds="[0,300][1080,900]">'
        '<node class="android.widget.TextView" text="Link Author" bounds="[0,310][500,360]"/>'
        '<node class="android.widget.TextView" text="4 giờ trước" bounds="[0,365][300,390]"/>'
        '<node class="android.widget.TextView" text="Đọc bài ở đây: https://example.com/article" bounds="[0,400][1080,450]"/>'
        "</node>"
    )
    xml = _recycler_xml(post_xml + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    link_posts = [p for p in posts if p["post_type"] == "link"]
    assert len(link_posts) == 1


# ── comment_preview ───────────────────────────────────────────────────────────


def test_comment_preview_captured():
    """Text appearing after engagement metrics → captured in comment_preview."""
    post_xml = (
        '<node class="android.view.ViewGroup" bounds="[0,300][1080,1100]">'
        '<node class="android.widget.TextView" text="Comment Author" bounds="[0,310][500,360]"/>'
        '<node class="android.widget.TextView" text="1 giờ trước" bounds="[0,365][300,390]"/>'
        '<node class="android.widget.TextView" text="Bài viết thú vị lắm" bounds="[0,400][1080,450]"/>'
        '<node class="android.widget.TextView" text="500" bounds="[0,600][100,630]"/>'
        '<node class="android.widget.TextView" text="30 bình luận" bounds="[110,600][300,630]"/>'
        '<node class="android.widget.TextView" text="Bình luận hay nhất của người dùng đây" bounds="[0,700][1080,750]"/>'
        "</node>"
    )
    xml = _recycler_xml(post_xml + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    assert len(posts) >= 1
    post = next(p for p in posts if p["author"] == "Comment Author")
    assert post["comment_preview"] is not None
    assert "Bình luận hay nhất" in post["comment_preview"]


# ── No timestamp → no post ────────────────────────────────────────────────────


def test_extract_post_no_timestamp_returns_none():
    """Cluster without any timestamp node → _extract_post returns None."""
    cluster = [
        {"text": "Author Name", "bounds": (0, 300, 500, 350), "cy": 325, "resource_id": ""},
        {"text": "Nội dung bài viết không có timestamp", "bounds": (0, 360, 1080, 410), "cy": 385, "resource_id": ""},
    ]
    result = _extract_post(cluster, source_index=0)
    assert result is None


# ── Noise-only cluster ────────────────────────────────────────────────────────


def test_extract_post_noise_only_returns_none():
    """Cluster where all text is noise → _extract_post returns None."""
    cluster = [
        {"text": "like", "bounds": (0, 300, 100, 330), "cy": 315, "resource_id": ""},
        {"text": "comment", "bounds": (110, 300, 250, 330), "cy": 315, "resource_id": ""},
        {"text": "share", "bounds": (260, 300, 400, 330), "cy": 315, "resource_id": ""},
    ]
    result = _extract_post(cluster, source_index=0)
    assert result is None


# ── Malformed XML ─────────────────────────────────────────────────────────────


def test_malformed_xml_returns_empty_list():
    """Malformed XML string → returns [] with no exception raised."""
    result = parse_fb_posts_from_xml("not valid xml")
    assert result == []


def test_empty_string_returns_empty_list():
    result = parse_fb_posts_from_xml("")
    assert result == []


# ── Deduplication ─────────────────────────────────────────────────────────────


def test_dedup_removes_identical_posts():
    """Two identical posts → _dedup returns only 1."""
    post = {
        "author": "Alice",
        "timestamp": "2 giờ trước",
        "text": "Bài viết gốc",
        "reactions": None,
        "comments": None,
        "shares": None,
        "source_index": 0,
        "post_type": "text",
        "image_desc": None,
        "comment_preview": None,
    }
    result = _dedup([post, post.copy()])
    assert len(result) == 1


def test_dedup_keeps_different_posts():
    """Two posts with different authors → both kept."""
    post_a = {
        "author": "Alice",
        "timestamp": "2 giờ trước",
        "text": "Post A",
        "reactions": None,
        "comments": None,
        "shares": None,
        "source_index": 0,
        "post_type": "text",
        "image_desc": None,
        "comment_preview": None,
    }
    post_b = {
        "author": "Bob",
        "timestamp": "2 giờ trước",
        "text": "Post B",
        "reactions": None,
        "comments": None,
        "shares": None,
        "source_index": 0,
        "post_type": "text",
        "image_desc": None,
        "comment_preview": None,
    }
    result = _dedup([post_a, post_b])
    assert len(result) == 2


# ── source_index passed through ───────────────────────────────────────────────


def test_source_index_passed_through():
    """source_index value is propagated to each post dict."""
    xml = _recycler_xml(_POST_A + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=7)
    assert all(p["source_index"] == 7 for p in posts)


# ── Timestamp regex patterns ──────────────────────────────────────────────────


@pytest.mark.parametrize("ts_string", [
    "2 giờ trước",
    "yesterday",
    "3 minutes ago",
    "hôm qua",
    "01/01/2024",
    "5 phút trước",
    "1 ngày trước",
    "just now",
    "2024-12-31",
    "1 hour ago",
    "T2, 01/01/2024",
])
def test_re_ts_matches_timestamp(ts_string: str):
    assert _RE_TS.search(ts_string) is not None, f"_RE_TS did not match: {ts_string!r}"


def test_re_ts_no_match_for_plain_text():
    assert _RE_TS.search("Hôm nay trời đẹp quá") is None
    assert _RE_TS.search("Bài viết bình thường") is None


# ── _is_noise_text ────────────────────────────────────────────────────────────


def test_is_noise_text_like_lowercase():
    assert _is_noise_text("like") is True


def test_is_noise_text_thich_case_insensitive():
    assert _is_noise_text("Thích") is True
    assert _is_noise_text("THÍCH") is True


def test_is_noise_text_share():
    assert _is_noise_text("share") is True
    assert _is_noise_text("chia sẻ") is True


def test_is_noise_text_real_content():
    assert _is_noise_text("Hôm nay trời đẹp") is False
    assert _is_noise_text("Bài viết thú vị") is False


def test_is_noise_text_empty():
    assert _is_noise_text("") is True
    assert _is_noise_text("   ") is True


def test_is_noise_text_dot_separator():
    assert _is_noise_text("·") is True


# ── _parse_bounds ─────────────────────────────────────────────────────────────


def test_parse_bounds_valid():
    node = _node(bounds="[10,20][100,200]")
    result = _parse_bounds(node)
    assert result == (10, 20, 100, 200)


def test_parse_bounds_no_attribute():
    node = _lxml.Element("node")
    # no bounds attribute at all
    result = _parse_bounds(node)
    assert result is None


def test_parse_bounds_malformed():
    node = _node(bounds="invalid")
    result = _parse_bounds(node)
    assert result is None


# ── Ad container skipped ──────────────────────────────────────────────────────


def test_ad_container_skipped_by_strategy_a():
    """RecyclerView child with sponsored_label resource-id → skipped, no post returned."""
    ad_post_xml = (
        '<node class="android.view.ViewGroup" bounds="[0,300][1080,900]">'
        '<node class="android.widget.TextView" text="Sponsored" '
        'resource-id="com.facebook.katana:id/sponsored_label" bounds="[0,310][200,340]"/>'
        '<node class="android.widget.TextView" text="Ad Author" bounds="[0,345][500,395]"/>'
        '<node class="android.widget.TextView" text="2 giờ trước" bounds="[0,400][300,425]"/>'
        '<node class="android.widget.TextView" text="Mua ngay sản phẩm" bounds="[0,430][1080,480]"/>'
        "</node>"
    )
    # RecyclerView needs at least 2 direct children to not fall back
    xml = _recycler_xml(ad_post_xml + _POST_B)
    posts = parse_fb_posts_from_xml(xml, source_index=0)
    # The ad post should be skipped; only _POST_B should remain
    assert all(p["author"] != "Ad Author" for p in posts)


# ── _collect_text_nodes ───────────────────────────────────────────────────────


def test_collect_text_nodes_sorted_by_cy():
    """_collect_text_nodes returns nodes sorted top-to-bottom by vertical centre."""
    root = _lxml.Element("root")
    root.append(_node(text="Bottom text", bounds="[0,800][500,850]"))
    root.append(_node(text="Top text", bounds="[0,300][500,350]"))
    root.append(_node(text="Middle text", bounds="[0,550][500,600]"))

    nodes = _collect_text_nodes(root, toolbar_cutoff_y=0)
    texts = [n["text"] for n in nodes]
    assert texts == ["Top text", "Middle text", "Bottom text"]


def test_collect_text_nodes_skips_toolbar():
    """Nodes above toolbar_cutoff_y are excluded."""
    root = _lxml.Element("root")
    root.append(_node(text="Status bar text", bounds="[0,10][500,50]"))
    root.append(_node(text="Content text", bounds="[0,300][500,350]"))

    nodes = _collect_text_nodes(root, toolbar_cutoff_y=200)
    texts = [n["text"] for n in nodes]
    assert "Status bar text" not in texts
    assert "Content text" in texts


# ── _cluster_into_posts ───────────────────────────────────────────────────────


def test_cluster_into_posts_empty():
    assert _cluster_into_posts([]) == []


def test_cluster_splits_on_large_gap():
    """Nodes with gap > 160 px between them → separate clusters."""
    nodes = [
        {"text": "Author 1", "cy": 300, "bounds": (0, 280, 500, 320), "resource_id": ""},
        {"text": "1 giờ trước", "cy": 340, "bounds": (0, 320, 300, 360), "resource_id": ""},
        # Large gap: 340 + 200 = 540 > 340+160
        {"text": "Author 2", "cy": 560, "bounds": (0, 540, 500, 580), "resource_id": ""},
        {"text": "2 giờ trước", "cy": 600, "bounds": (0, 580, 300, 620), "resource_id": ""},
    ]
    clusters = _cluster_into_posts(nodes)
    assert len(clusters) == 2
