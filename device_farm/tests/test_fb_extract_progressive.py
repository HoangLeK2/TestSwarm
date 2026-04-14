"""Unit tests for progressive 'See more' expansion in fb_extract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch

from tasks.fb_extract import (
    _cluster_into_posts,
    _collect_see_more_tap_plan,
    _expand_see_more,
    _dedup,
    _extract_comment,
    _normalize_fb_ui_spacing,
    _parse_xml,
    _RE_LINK_TYPE,
    _maybe_fix_merged_feed_caption,
    _refresh_post_derived_hashes,
    expand_see_more_with_lazy_hydration,
    is_fb_post_truncated,
    parse_fb_posts_from_xml,
)


def _xml_with_clickables(*, texts: List[str] | None = None, descs: List[str] | None = None) -> str:
    texts = texts or []
    descs = descs or []
    nodes: List[str] = []
    y = 300
    for t in texts:
        nodes.append(
            f'<node class="android.widget.Button" clickable="true" text="{t}" '
            f'content-desc="" bounds="[100,{y}][500,{y + 80}]"/>'
        )
        y += 120
    for d in descs:
        nodes.append(
            f'<node class="android.widget.Button" clickable="true" text="" '
            f'content-desc="{d}" bounds="[100,{y}][500,{y + 80}]"/>'
        )
        y += 120
    body = "\n".join(nodes) if nodes else '<node class="android.widget.TextView" text="noop" bounds="[0,300][100,340]"/>'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
{body}
</hierarchy>"""


@dataclass
class _FakeDevice:
    xml_sequence: List[str]
    xml_calls: int = 0
    taps: List[tuple[int, int]] = field(default_factory=list)
    scrolls: List[tuple[str, float]] = field(default_factory=list)

    def hierarchy_xml(self, force_refresh: bool = True) -> str:
        idx = min(self.xml_calls, len(self.xml_sequence) - 1)
        self.xml_calls += 1
        return self.xml_sequence[idx]

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def scroll(self, direction: str, distance: float, *, duration_ms: int = 400) -> None:
        self.scrolls.append((direction, distance))


def test_merged_feed_caption_strips_second_post_header_after_see_more():
    """Hai preview dính `` ** `` — bỏ phần timestamp/ghép nhầm sau Xem thêm."""
    p = {
        "author": "Le Anh Duc",
        "text": (
            "Một repo đang hot … Xem thêm 1 ngày•Chia sẻ với: Công khai "
            "**Một tool hữu ích cho Openclaw … Xem thêm"
        ),
        "image_desc": None,
        "comment_preview": None,
    }
    _maybe_fix_merged_feed_caption(p)
    _refresh_post_derived_hashes(p)
    assert " ** " not in p["text"]
    assert "Một tool hữu ích" not in p["text"]
    assert p["text"].rstrip().endswith("Xem thêm")


def test_is_fb_post_truncated_detects_markers():
    assert is_fb_post_truncated({"text": "Hello see more"})
    assert is_fb_post_truncated({"text": "Xem thêm ở đây"})
    assert not is_fb_post_truncated({"text": "Full body only."})


def test_lazy_hydration_stops_when_xml_unchanged():
    """No See-more targets → no scroll (avoids shoving feed on short posts)."""
    same = _xml_with_clickables()
    device = _FakeDevice(xml_sequence=[same, same])

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        n = expand_see_more_with_lazy_hydration(device, max_rounds=6, scroll_distance=0.2)

    assert n == 0
    assert device.scrolls == []
    assert device.xml_calls <= 3


def test_lazy_hydration_taps_see_more_without_feed_scroll():
    """Lazy hydration taps See more but never scrolls the feed between rounds."""
    a = _xml_with_clickables(texts=["Xem thêm"])
    b = _xml_with_clickables(texts=["noop"])
    device = _FakeDevice(xml_sequence=[a, a, b, b])

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        n = expand_see_more_with_lazy_hydration(
            device,
            max_rounds=4,
            scroll_distance=0.15,
        )

    assert n >= 1
    assert device.scrolls == []


def test_expand_see_more_progressive_long_post_multi_stage():
    """Simulate long post that reveals more 'Xem thêm' in multiple stages."""
    device = _FakeDevice(
        xml_sequence=[
            _xml_with_clickables(texts=["Xem thêm"]),  # pass 1
            _xml_with_clickables(texts=["Xem thêm"]),  # pass 2 after scroll
            _xml_with_clickables(),                    # pass 3 no candidate
            _xml_with_clickables(),                    # pass 4 no candidate -> stop
        ]
    )

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(
            device,
            max_passes=6,
            scroll_between=True,
            scroll_distance=0.22,
            no_change_threshold=2,
        )

    assert expanded == 2
    assert len(device.taps) == 2
    assert any(d == ("down", 0.22) for d in device.scrolls)


def test_collect_see_more_dedupes_near_duplicate_xem_them_nodes():
    """Two a11y nodes for the same control (offset bounds) must not produce two taps."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.Button" clickable="true" text="Xem thêm"
    bounds="[100,500][300,560]"/>
  <node class="android.widget.TextView" clickable="true" text="Xem thêm"
    bounds="[104,502][296,558]"/>
</hierarchy>"""
    root = _parse_xml(xml)
    assert root is not None
    plan = _collect_see_more_tap_plan(root)
    assert len(plan) == 1


def test_expand_see_more_supports_content_desc_candidates():
    """Facebook sometimes exposes labels via content-desc instead of text."""
    device = _FakeDevice(
        xml_sequence=[
            _xml_with_clickables(descs=["Xem thêm"]),
            _xml_with_clickables(),
        ]
    )

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(device, max_passes=2, scroll_between=False)

    assert expanded == 1
    assert len(device.taps) == 1


def test_expand_see_more_supports_comment_pagination_labels():
    """Should also tap 'xem thêm bình luận/câu trả lời' labels."""
    # One tap per hierarchy refresh — simulate reflow: first dump has both, second only one left.
    a = _xml_with_clickables(texts=["Xem thêm bình luận", "Xem thêm câu trả lời"])
    b = _xml_with_clickables(texts=["Xem thêm câu trả lời"])
    device = _FakeDevice(xml_sequence=[a, b, _xml_with_clickables()])

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(device, max_passes=2, scroll_between=False)

    assert expanded == 2
    assert len(device.taps) == 2


def test_expand_see_more_respects_max_total_taps_limit():
    """Guard against over-tapping when many expandable nodes are present."""
    # Each dump yields one target; stale multi-target plans are no longer multi-tapped.
    one = _xml_with_clickables(texts=["Xem thêm"])
    device = _FakeDevice(xml_sequence=[one, one, one, one, _xml_with_clickables()])

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(
            device,
            max_passes=5,
            max_total_taps=4,
            scroll_between=False,
        )

    assert expanded == 4
    assert len(device.taps) == 4


def test_expand_see_more_taps_clickable_ancestor_when_label_not_clickable():
    """FB can render 'Xem thêm' as non-clickable child under clickable parent."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.view.ViewGroup" clickable="true" bounds="[100,300][500,380]">
    <node class="android.widget.TextView" clickable="false" text="Xem thêm" content-desc="" bounds="[120,320][260,350]"/>
  </node>
</hierarchy>"""
    device = _FakeDevice(xml_sequence=[xml, _xml_with_clickables()])

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(device, max_passes=2, scroll_between=False)

    assert expanded == 1
    assert len(device.taps) == 1
    # Tap should target parent clickable container center: (300, 340)
    assert device.taps[0] == (300, 340)


def test_expand_see_more_prefers_inner_button_over_wrapping_post_body():
    """Full post row is clickable; real 'Xem thêm' is a small Button — tap that, not row center."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.view.ViewGroup" clickable="true" text="Post … Xem thêm" bounds="[42,200][1200,400]">
    <node class="android.widget.Button" clickable="true" text="Xem thêm" bounds="[900,300][1100,370]"/>
  </node>
</hierarchy>"""
    device = _FakeDevice(xml_sequence=[xml, _xml_with_clickables()])

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(device, max_passes=2, scroll_between=False)

    assert expanded == 1
    assert len(device.taps) == 1
    assert device.taps[0] == (1000, 335)


def test_dedup_prefers_expanded_post_over_truncated_preview():
    truncated = {
        "author": "Huyền Lê",
        "timestamp": "1 ngày",
        "text": "Mình vừa thử cách host OpenClaw mới và nó giải quyết đúng cái đau đầu nhất của mình.… Xem thêm",
        "reactions": None,
        "comments": None,
        "shares": None,
        "views": None,
        "image_desc": None,
        "comment_preview": None,
    }
    expanded = {
        "author": "Huyền Lê",
        "timestamp": "1 ngày",
        "text": (
            "Mình vừa thử cách host OpenClaw mới và nó giải quyết đúng cái đau đầu nhất của mình. "
            "Đầu tiên là setup nhanh, sau đó ổn định hơn khi chạy dài. "
            "Nếu ai đang gặp vấn đề timeout thì nên thử GreenNode."
        ),
        "reactions": "12",
        "comments": "3",
        "shares": None,
        "views": None,
        "image_desc": "Ảnh",
        "comment_preview": None,
    }

    out = _dedup([truncated, expanded])
    assert len(out) == 1
    assert "Xem thêm" not in out[0]["text"]
    assert len(out[0]["text"]) > len(truncated["text"])


def test_dedup_stable_post_id_ignores_timestamp_variation():
    p1 = {
        "author": "A",
        "timestamp": "1 giờ",
        "text": "Nội dung rất dài đã bung full",
        "stable_post_id": "sid",
        "post_key": "k1",
    }
    p2 = {
        "author": "A",
        "timestamp": "59 phút",
        "text": "Nội dung rất dài đã bung full",
        "stable_post_id": "sid",
        "post_key": "k2",
    }
    out = _dedup([p1, p2])
    assert len(out) == 1


def test_parse_posts_staggered_grid_surface_view_implies_video():
    """StaggeredGrid feed + SurfaceView → video without locale-specific labels."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.StaggeredGridLayoutManager" scrollable="true"
        bounds="[0,0][1080,2200]">
    <node bounds="[0,200][1080,900]">
      <node class="android.view.SurfaceView" bounds="[0,220][1080,700]"/>
      <node text="Jane" bounds="[40,720][120,760]"/>
      <node text="Caption without the r-word token" bounds="[40,770][500,810]"/>
      <node text="3 min" bounds="[40,820][100,850]"/>
    </node>
    <node bounds="[0,950][1080,1100]">
      <node text="Other" bounds="[40,970][120,1010]"/>
      <node text="Second card" bounds="[40,1020][300,1060]"/>
      <node text="1 min" bounds="[40,1070][100,1100]"/>
    </node>
  </node>
</hierarchy>"""
    posts = parse_fb_posts_from_xml(xml)
    jane = next(p for p in posts if p.get("author") == "Jane")
    assert jane["post_type"] == "video"
    assert len(posts) >= 1


def test_parse_posts_carousel_media_artifacts_match_recycler_child():
    """Ảnh 1/3 … live under the same RecyclerView row as author+text; bounds for overlay on capture."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,287][1260,2800]">
    <node bounds="[0,287][1260,400]">
      <node text="Pad" bounds="[40,300][80,340]"/>
      <node text="1 min" bounds="[40,350][120,380]"/>
    </node>
    <node bounds="[0,1544][1260,2800]">
      <node class="android.widget.ImageView" content-desc="Ảnh đại diện của Lê Phan Trường Giang"
             bounds="[42,1586][182,1726]"/>
      <node class="android.widget.Button"
             content-desc="Lựa chọn khác cho bài viết của Lê Phan Trường Giang"
             bounds="[1113,1544][1260,1690]"/>
      <node class="android.view.ViewGroup" text="Hỏi Nhanh đáp gọn… Xem thêm"
             bounds="[42,1768][1218,1871]"/>
      <node class="android.widget.Button" content-desc="Ảnh 1/3, mở rộng ảnh"
             bounds="[0,1871][1260,2702]"/>
      <node class="android.widget.Button" content-desc="Ảnh 2/3, mở rộng ảnh"
             bounds="[0,2713][625,2800]"/>
      <node class="android.widget.Button" content-desc="Ảnh 3/3, mở rộng ảnh"
             bounds="[635,2713][1260,2800]"/>
    </node>
  </node>
</hierarchy>"""
    posts = parse_fb_posts_from_xml(xml)
    car = next((p for p in posts if p.get("author") == "Lê Phan Trường Giang"), None)
    assert car is not None
    assert car.get("feed_item_index") == 1
    arts = car.get("media_artifacts") or []
    assert len(arts) == 3
    assert [a["slot"] for a in arts] == [1, 2, 3]
    assert all(a["total"] == 3 for a in arts)
    assert arts[0]["bounds"] == [0, 1871, 1260, 2702]
    assert "Ảnh 2/3" not in (car.get("text") or "")
    assert car.get("post_type") == "photo"


def test_parse_posts_without_timestamp_uses_action_row_anchor():
    """FB sometimes omits '5 giờ' / '1 ngày' — body sits between media and Thích/Bình luận."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,287][1260,2800]">
    <node bounds="[0,287][1260,1544]">
      <node class="android.widget.ImageView" content-desc="Ảnh đại diện của Phan Đình Long"
             bounds="[42,322][182,462]"/>
      <node class="android.widget.Button"
             content-desc="Lựa chọn khác cho bài viết của Phan Đình Long"
             bounds="[1113,287][1260,426]"/>
      <node class="android.view.ViewGroup" content-desc="Hình minh họa màu hồng, phông nền"
             clickable="true" bounds="[42,504][1218,1376]"/>
      <node class="android.view.ViewGroup" text="Có ai dùng Open Claw để trading và lên kế hoạch trade chưa cho em xin ý kiến với ạ"
             content-desc="Có ai dùng Open Claw để trading và lên kế hoạch trade chưa cho em xin ý kiến với ạ"
             bounds="[105,641][1155,1246]"/>
      <node class="android.widget.Button" text="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận."
             bounds="[0,1376][252,1530]"/>
      <node class="android.widget.Button" text="Bình luận" content-desc="Bình luận"
             bounds="[252,1376][481,1530]"/>
    </node>
    <node bounds="[0,1544][1260,1768]">
      <node text="Other" bounds="[40,1586][120,1626]"/>
      <node text="2 min" bounds="[40,1700][120,1730]"/>
    </node>
  </node>
</hierarchy>"""
    posts = parse_fb_posts_from_xml(xml)
    long_post = next(
        (p for p in posts if "Open Claw" in (p.get("text") or "")), None
    )
    assert long_post is not None
    assert long_post.get("author") == "Phan Đình Long"
    assert "trading" in (long_post.get("text") or "").lower()
    assert (long_post.get("image_desc") or "").startswith("Hình")


def test_parse_posts_extracts_fb_ids_from_visible_url():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.StaggeredGridLayoutManager" scrollable="true"
        bounds="[0,0][1080,2200]">
    <node bounds="[0,200][1080,800]">
      <node text="Mod" bounds="[40,240][100,280]"/>
      <node text="See https://www.facebook.com/groups/999888777/posts/12345678901234567 ok"
            bounds="[40,300][1000,380]"/>
      <node text="1 hr" bounds="[40,400][120,430]"/>
    </node>
    <node bounds="[0,820][1080,980]">
      <node text="X" bounds="[40,840][80,880]"/>
      <node text="Noise" bounds="[40,900][200,940]"/>
      <node text="5 min" bounds="[40,950][120,980]"/>
    </node>
  </node>
</hierarchy>"""
    posts = parse_fb_posts_from_xml(xml)
    with_url = [p for p in posts if p.get("fb_post_id")]
    assert len(with_url) == 1
    p = with_url[0]
    assert p["fb_group_id"] == "999888777"
    assert p["fb_post_id"] == "12345678901234567"
    assert p["permalink_candidates"]
    assert p["post_type"] == "link"


def test_recycler_prefers_tall_wide_feed_over_short_strip():
    """Short nested RecyclerView (e.g. stories) should not win over main grid."""
    buttons = "\n".join(
        f'<node class="android.widget.Button" text="S{i}" bounds="[{50+i*40},1210][{80+i*40},1290]"/>'
        for i in range(8)
    )
    posts_block = "\n".join(
        f'<node bounds="[0,{300+i*400}][1080,{650+i*400}]">'
        f'<node text="U{i}" bounds="[40,{320+i*400}][120,{360+i*400}]"/>'
        f'<node text="Hello {i}" bounds="[40,{380+i*400}][500,{420+i*400}]"/>'
        f'<node text="2 min" bounds="[40,{440+i*400}][120,{470+i*400}]"/>'
        f"</node>"
        for i in range(3)
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"
        bounds="[0,1200][1080,1310]">
    {buttons}
  </node>
  <node class="androidx.recyclerview.widget.StaggeredGridLayoutManager" scrollable="true"
        bounds="[0,200][1080,2200]">
    {posts_block}
  </node>
</hierarchy>"""
    posts = parse_fb_posts_from_xml(xml)
    assert len(posts) == 3
    authors = {p["author"] for p in posts}
    assert authors == {"U0", "U1", "U2"}


def test_dedup_keeps_distinct_posts_when_stable_id_collides():
    p1 = {
        "author": "A",
        "timestamp": "1 giờ",
        "text": "Bài thứ nhất mở đầu giống nhau nhưng phần sau khác hẳn",
        "stable_post_id": "same-sid",
        "post_key": "k1",
    }
    p2 = {
        "author": "A",
        "timestamp": "2 giờ",
        "text": "Bài thứ hai mở đầu giống nhau nhưng nội dung về chủ đề hoàn toàn khác",
        "stable_post_id": "same-sid",
        "post_key": "k2",
    }
    out = _dedup([p1, p2])
    assert len(out) == 2


def test_extract_comment_drops_composer_placeholder_viet() -> None:
    cluster = [
        {"text": "Viết bình luận công khai...", "bounds": (200, 0, 500, 40)},
    ]
    assert _extract_comment(cluster, parent_post_id="p", cluster_min_x=200) is None


def test_extract_comment_name_dot_badge_then_body() -> None:
    cluster = [
        {"text": "Lan Anh • Quan tâm", "bounds": (200, 0, 400, 40)},
        {"text": "Nội dung comment đủ dài ở đây", "bounds": (200, 50, 400, 90)},
    ]
    c = _extract_comment(cluster, parent_post_id="pid", cluster_min_x=200)
    assert c is not None
    assert c["author"] == "Lan Anh"
    assert c.get("badges") and any("quan tâm" in b.lower() for b in c["badges"])
    assert "Nội dung" in c["text"]


def test_normalize_fb_ui_spacing_replaces_nbsp() -> None:
    assert _normalize_fb_ui_spacing("Tham\xa0gia") == "Tham gia"
    assert " " in _normalize_fb_ui_spacing("OpenClaw VN\xa0· Truy\xa0cập")


def test_re_link_type_matches_fb_short_urls() -> None:
    assert _RE_LINK_TYPE.search("xem https://fb.watch/abcxyz tail")
    assert _RE_LINK_TYPE.search("nhắn https://m.me/somepage đi")
    assert _RE_LINK_TYPE.search("https://l.facebook.com/l.php?u=...")


def test_cluster_into_posts_merges_long_vertical_gap_same_left_margin() -> None:
    """Hai đoạn body xa nhau dọc nhưng cùng lề — vẫn một cluster."""
    nodes = [
        {
            "text": "A" * 40 + " đoạn mở đầu bài viết đủ dài để không bị gộp nhầm tên.",
            "bounds": (40, 80, 1000, 120),
            "cy": 100,
            "resource_id": "",
            "is_author_hint": False,
        },
        {
            "text": "B" * 40 + " đoạn tiếp theo cùng bài, layout FB tách xa.",
            "bounds": (42, 400, 1000, 440),
            "cy": 420,
            "resource_id": "",
            "is_author_hint": False,
        },
    ]
    clusters = _cluster_into_posts(nodes, screen_height=2200)
    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_extract_comment_refine_author_longer_like_button_prefix() -> None:
    cluster = [
        {"text": "Van", "bounds": (200, 0, 300, 40)},
        {"text": "Reply text with enough characters in the body", "bounds": (200, 50, 500, 90)},
        {"text": "Nút Thích bình luận của Van Nguyen.", "bounds": (200, 100, 500, 140)},
    ]
    c = _extract_comment(cluster, parent_post_id="p", cluster_min_x=200)
    assert c is not None
    assert c["author"] == "Van Nguyen"
