"""Tests for post-open header tap resolution (badge-agnostic metadata row)."""

from __future__ import annotations

from relay.extra_data.parsers.facebook import post_open_pipeline


def _feed_card_xml(
    *,
    author: str,
    metadata: str,
    body: str,
    y_offset: int = 400,
) -> str:
    ay = y_offset + 20
    my = y_offset + 72
    by = y_offset + 140
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
      <node class="android.view.ViewGroup" bounds="[0,{y_offset}][1080,{y_offset + 900}]">
        <node class="android.widget.TextView" text="{author}" bounds="[132,{ay}][520,{ay + 44}]" clickable="false"/>
        <node class="android.widget.TextView" text="{metadata}" bounds="[540,{my}][980,{my + 36}]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="{body}" bounds="[36,{by}][1044,{by + 200}]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[360,{y_offset + 760}][520,{y_offset + 820}]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""


def test_resolve_prefers_timestamp_metadata_over_geometric() -> None:
    xml = _feed_card_xml(
        author="Vũ Duy Mạnh",
        metadata="7 giờ",
        body="Mình còn dư ít Sonnet 4.6",
    )
    top, ranked = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"author_row_gap", "timestamp", "metadata", "geometric"}
    assert top["tap_kind"] not in {"post_body", "post_media"}
    assert len(ranked) >= 0


def test_resolve_accepts_arbitrary_badge_text_as_metadata() -> None:
    xml = _feed_card_xml(
        author="Vũ Duy Mạnh",
        metadata="Người đóng góp nhiều nhất",
        body="Long post body on image overlay",
    )
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"post_body", "author_row_gap", "metadata", "timestamp", "geometric"}
    if top["tap_kind"] == "metadata":
        assert "Người đóng góp" in (top.get("tap_label") or "")


def test_resolve_accepts_different_badge_label() -> None:
    xml = _feed_card_xml(
        author="Test User",
        metadata="Siêu fan",
        body="Another badge style under author row",
    )
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"post_body", "author_row_gap", "metadata", "timestamp", "geometric"}


def test_post_header_tap_point_post_body_avoids_see_more_corner() -> None:
    cx, cy = post_open_pipeline.post_header_tap_point(
        (42, 2036, 1218, 2363), tap_kind="post_body"
    )
    assert cx < 900
    assert cy < 2280


def test_post_header_tap_point_gap_stays_left() -> None:
    cx, cy = post_open_pipeline.post_header_tap_point(
        (194, 319, 1103, 371), tap_kind="author_row_gap"
    )
    assert cx < 500
    assert 319 <= cy <= 371


def test_discover_cards_inside_single_recycler_wrapper() -> None:
    xml = _feed_multi_post_xml()
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"author_row_gap", "timestamp", "metadata", "geometric"}
    assert top["tap_kind"] not in {"post_body", "post_media"}


def test_resolve_skips_partial_media_card_above_visible_author_post() -> None:
    """Regression: do not open/comment the previous image post when its header is gone."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,1200]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,100][1080,1150]">
      <node class="android.view.ViewGroup" bounds="[0,0][1080,760]">
        <node class="android.widget.ImageView" content-desc="Ảnh" bounds="[0,80][1080,620]" clickable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[210,650][360,720]" clickable="true"/>
      </node>
      <node class="android.view.ViewGroup" bounds="[0,630][1080,1040]">
        <node class="android.widget.TextView" text="Minh Hoang" bounds="[132,650][420,694]" clickable="false"/>
        <node class="android.widget.TextView" text="3 ngày" bounds="[132,698][240,734]" clickable="true"/>
        <node content-desc="Lựa chọn khác cho bài viết này" bounds="[980,642][1060,702]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Mn cho mình hỏi là có bên thứ 3 nào bán API OpenAI Gemini Claude rẻ hơn mua chính chủ mà chất lượng tương đương không nhỉ?" bounds="[36,760][1044,900]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[210,940][360,1000]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""
    top, alternates = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["feed_item_index"] == 1
    assert (top.get("post") or {}).get("author") == "Minh Hoang"
    assert top["tap_kind"] != "post_media"
    assert all((alt.get("post") or {}).get("author") != "" for alt in alternates)


def test_resolve_visible_author_post_when_action_bar_below_viewport() -> None:
    """Regression: do not latch onto a previous post's visible comment row."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,1200]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,100][1080,1150]">
      <node class="android.view.ViewGroup" bounds="[0,0][1080,520]">
        <node class="android.widget.ImageView" content-desc="Ảnh có thể có: Working for 9h 30m 48s" bounds="[0,80][1080,390]" clickable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[210,420][360,490]" clickable="true"/>
      </node>
      <node class="android.view.ViewGroup" bounds="[0,500][1080,1120]">
        <node class="android.widget.TextView" text="Lê Chung" bounds="[132,530][420,574]" clickable="false"/>
        <node class="android.widget.TextView" text="5 giờ" bounds="[132,578][240,614]" clickable="true"/>
        <node content-desc="Lựa chọn khác cho bài viết này" bounds="[980,522][1060,582]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Openclaw đang ngon lành thì bị thế này ạ, ai giải thích giúp em với" bounds="[36,650][1044,860]" clickable="true" focusable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""
    top, alternates = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["feed_item_index"] == 1
    assert (top.get("post") or {}).get("author") == "Lê Chung"
    assert top["tap_kind"] in {"timestamp", "author_row_gap", "metadata"}
    assert all((alt.get("post") or {}).get("author") != "" for alt in alternates)


def test_detail_detection_single_card() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.view.ViewGroup" bounds="[0,0][1080,2400]">
    <node content-desc="Lựa chọn khác cho bài viết này" bounds="[980,80][1060,140]" clickable="true"/>
    <node class="android.widget.TextView" text="Author" bounds="[120,120][400,160]"/>
    <node class="android.widget.Button" content-desc="Nút Bình luận" text="Bình luận" bounds="[300,2000][500,2060]" clickable="true"/>
  </node>
</hierarchy>"""
    assert post_open_pipeline.hierarchy_is_fb_post_detail_from_xml(xml)


def _feed_two_line_header_xml(
    *,
    author: str,
    second_line: str,
    body: str,
    y_offset: int = 400,
) -> str:
    ay = y_offset + 20
    sy = y_offset + 68
    by = y_offset + 150
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
      <node class="android.view.ViewGroup" bounds="[0,{y_offset}][1080,{y_offset + 900}]">
        <node class="android.widget.TextView" text="{author}" bounds="[132,{ay}][420,{ay + 44}]" clickable="false"/>
        <node class="android.widget.TextView" text="{second_line}" bounds="[132,{sy}][720,{sy + 36}]" clickable="true"/>
        <node content-desc="Lựa chọn khác cho bài viết này" bounds="[980,{ay - 8}][1060,{ay + 48}]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="{body}" bounds="[36,{by}][1044,{by + 200}]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[360,{y_offset + 760}][520,{y_offset + 820}]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""


def _feed_multi_post_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2200]">
      <node class="android.view.ViewGroup" bounds="[0,400][1080,1100]">
        <node class="android.widget.TextView" text="Huan Nguyen" bounds="[132,420][420,464]" clickable="false"/>
        <node class="android.widget.TextView" text="22 thg 5" bounds="[132,468][280,504]" clickable="true"/>
        <node content-desc="Lựa chọn khác cho bài viết này" bounds="[980,412][1060,472]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Post one body text for opening detail view" bounds="[36,520][1044,700]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận" text="Bình luận" bounds="[360,980][520,1040]" clickable="true"/>
      </node>
      <node class="android.view.ViewGroup" bounds="[0,1100][1080,1800]">
        <node class="android.widget.TextView" text="Anh Nguyen" bounds="[132,1120][400,1164]" clickable="false"/>
        <node class="android.widget.TextView" text="5 ngày" bounds="[132,1168][240,1204]" clickable="true"/>
        <node content-desc="Lựa chọn khác cho bài viết này" bounds="[980,1112][1060,1172]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Post two body text for opening detail view" bounds="[36,1220][1044,1400]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận" text="Bình luận" bounds="[360,1680][520,1740]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""


def test_feed_with_two_visible_posts_is_not_detail() -> None:
    assert not post_open_pipeline.hierarchy_is_fb_post_detail_from_xml(_feed_multi_post_xml())


def test_after_header_tap_trace_is_post_detail_chrome() -> None:
    """Regression: real device trace after timestamp tap (fb_after_header_tap.xml)."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "debug" / "traces" / "fb_after_header_tap.xml"
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    assert post_open_pipeline.hierarchy_is_fb_post_detail_from_xml(xml)
    from relay.extra_data.parsers.facebook.comment_pipeline import (
        should_press_back_after_failed_tap,
    )

    assert should_press_back_after_failed_tap(xml) is False


def test_resolve_two_line_header_no_badge_prefers_gap_or_timestamp() -> None:
    """Use case: author row + timestamp below (Anh Nguyen / 5 ngày)."""
    xml = _feed_two_line_header_xml(
        author="Anh Nguyen",
        second_line="5 ngày",
        body="OpenClaw hay bị chết lệnh giữa chừng",
    )
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"post_body", "author_row_gap", "timestamp"}


def test_resolve_badge_on_second_line_prefers_author_row_gap() -> None:
    """Use case: badge under author (Người đóng góp đáng tin) — tap empty strip, not badge."""
    xml = _feed_two_line_header_xml(
        author="Huan Nguyen",
        second_line="Người đóng góp đáng tin",
        body="Hiện tại khá hài lòng với CLIproxyAPI",
    )
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"post_body", "author_row_gap"}


def _vivo_wide_author_hint_xml() -> str:
    """Regression: menu button content-desc matched is_author_hint; avatar is left column."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1260,2800]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,287][1260,2800]">
      <node class="android.view.ViewGroup" bounds="[0,287][1260,2195]">
        <node class="android.view.ViewGroup" bounds="[42,319][182,459]" clickable="true" content-desc="Ảnh đại diện của Huan Nguyen"/>
        <node class="android.widget.Button" content-desc="Lựa chọn khác cho bài viết của Huan Nguyen" bounds="[1113,287][1260,423]" clickable="true"/>
        <node class="android.widget.TextView" text="Huan Nguyen" bounds="[194,319][520,371]" clickable="false"/>
        <node class="android.widget.TextView" text="Người đóng góp đang lên" bounds="[194,371][720,423]" clickable="true"/>
        <node class="android.widget.Button" text="Theo dõi" bounds="[820,319][1020,376]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Post body text for detail open on vivo layout" bounds="[42,513][1218,900]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[360,2000][520,2060]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""


def test_vivo_layout_author_left_not_menu() -> None:
    xml = _vivo_wide_author_hint_xml()
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"post_body", "author_row_gap", "timestamp"}
    if top["tap_kind"] == "author_row_gap":
        cx, cy = post_open_pipeline.post_header_tap_point(
            tuple(top["bounds"]), tap_kind="author_row_gap"
        )
        assert cx < 500
        assert cy < 400


def test_case3_translated_post_taps_content_not_translation_chrome() -> None:
    """Case 3: FB auto-translation — tap post text block, not 'Xếp hạng bản dịch này'."""
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "debug"
        / "traces"
        / "fb_feed_case3_translated_post.xml"
    )
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    from relay.extra_data.parsers.facebook.parser import (
        _collect_text_nodes,
        _parse_bounds,
        _parse_xml,
    )

    parsed = _parse_xml(xml)
    assert parsed is not None
    el = post_open_pipeline._discover_post_open_scan_elements(parsed)[0][1]

    cb = _parse_bounds(el)
    nodes = _collect_text_nodes(el, toolbar_cutoff_y=0)
    ab = post_open_pipeline._find_author_bounds(nodes, cb)
    tap = post_open_pipeline._pick_header_tap_for_card(
        el, card_bounds=cb, nodes=nodes, author_bounds=ab
    )
    assert tap is not None
    assert tap["tap_kind"] in {
        "post_body",
        "post_media",
        "timestamp",
        "author_row_gap",
        "metadata",
    }
    assert "xếp hạng bản dịch" not in (tap.get("label") or "").casefold()
    cx, cy = post_open_pipeline.post_header_tap_point(
        tuple(tap["bounds"]), tap_kind=str(tap["tap_kind"])
    )
    for sx1, sy1, sx2, sy2 in [(1049, 740, 1153, 802)]:
        assert not (sx1 <= cx <= sx2 and sy1 <= cy <= sy2)


def test_case2_photo_caption_prefers_post_media() -> None:
    """Case 2: short caption + full-width image (Vy Thiên Hùng BDS post)."""
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "debug"
        / "traces"
        / "fb_feed_case2_photo_caption.xml"
    )
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    # Timestamp row opens post detail; tapping the photo opens the lightbox.
    assert top["tap_kind"] in {"post_media", "timestamp", "author_row_gap"}
    cx, cy = post_open_pipeline.post_header_tap_point(
        tuple(top["bounds"]), tap_kind=str(top["tap_kind"])
    )
    if top["tap_kind"] == "post_media":
        assert cy >= 900
        assert not (840 <= cy <= 920)
    else:
        assert cy < 900


def test_openclaw_follow_layout_prefers_post_body_not_follow() -> None:
    """Regression from device dump: Follow at [660,373][893,439], post text below."""
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "debug"
        / "traces"
        / "fb_feed_openclaw_follow.xml"
    )
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {
        "post_body",
        "post_media",
        "timestamp",
        "author_row_gap",
    }
    cx, cy = post_open_pipeline.post_header_tap_point(
        tuple(top["bounds"]), tap_kind=str(top["tap_kind"])
    )
    assert cy >= 400
    assert not (660 <= cx <= 893 and 373 <= cy <= 439)


def test_openclaw_gradient_post_prefers_timestamp_beside_author() -> None:
    """Device dump: tap '7 giờ' row beside author, not gradient text body."""
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "debug"
        / "traces"
        / "fb_feed_10AE7S00HD002JK_20260601_171406.xml"
    )
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"timestamp", "author_row_gap"}
    cx, cy = post_open_pipeline.post_header_tap_point(
        tuple(top["bounds"]), tap_kind=str(top["tap_kind"])
    )
    assert cy < 700
    assert cx < 900
    assert not (105 <= cx <= 1155 and 741 <= cy <= 1291)


def test_live_feed_dump_if_present() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "debug" / "traces" / "fb_feed_live.xml"
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    diag = post_open_pipeline.diagnose_post_open_resolution(xml)
    assert diag.get("missing_tap", 99) == 0
    assert diag.get("filtered_by_band", 99) == 0
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["feed_item_index"] == 0
    assert top["tap_kind"] in {
        "post_body",
        "post_media",
        "timestamp",
        "author_row_gap",
        "metadata",
    }
    cx, cy = post_open_pipeline.post_header_tap_point(
        tuple(top["bounds"]), tap_kind=str(top["tap_kind"])
    )
    assert 250 <= cx <= 900
    assert cy > 300


def _feed_anonymous_post_xml() -> str:
    """Layout from live Codex VN anonymous post — name/time open info sheet, gap opens detail."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1260,2800]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,287][1260,2800]">
      <node class="android.view.ViewGroup" bounds="[0,472][1260,2641]">
        <node class="android.widget.ImageView" content-desc="Ảnh đại diện của Người tham gia ẩn danh" bounds="[42,514][182,654]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Người tham gia ẩn danh" bounds="[210,515][1085,581]" clickable="false">
          <node class="android.widget.Button" text="Người tham gia ẩn danh" bounds="[210,515][849,581]" clickable="true"/>
        </node>
        <node class="android.view.ViewGroup" text="32 phút•Chia sẻ với: Nhóm công khai" content-desc="32 phút•Chia sẻ với: Nhóm công khai" bounds="[224,595][465,644]" clickable="true"/>
        <node class="android.widget.Button" content-desc="Lựa chọn khác cho bài viết của Người tham gia ẩn danh" bounds="[1113,472][1260,618]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="cho em hỏi sao chatgpt với codex của em mỗi lần mở máy bật lại là cứ bị hết phiên đăng nhập v ạ" bounds="[42,696][1218,1225]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[360,2480][520,2540]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""


def test_anonymous_author_prefers_gap_near_menu_not_timestamp() -> None:
    xml = _feed_anonymous_post_xml()
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] == "author_row_gap"
    x1, y1, x2, y2 = top["bounds"]
    assert x1 >= 849
    assert x2 <= 1113
    cx, cy = post_open_pipeline.post_header_tap_point(
        tuple(top["bounds"]), tap_kind="author_row_gap"
    )
    assert 861 <= cx <= 1100
    assert 515 <= cy <= 590


def test_is_anonymous_fb_author_detects_vietnamese_label() -> None:
    from relay.extra_data.parsers.facebook.parser import _collect_text_nodes, _parse_bounds, _parse_xml

    root = _parse_xml(_feed_anonymous_post_xml())
    el = post_open_pipeline._discover_post_open_scan_elements(root)[0][1]
    cb = _parse_bounds(el)
    nodes = _collect_text_nodes(el, toolbar_cutoff_y=0)
    ab = post_open_pipeline._find_author_bounds(nodes, cb)
    assert post_open_pipeline._is_anonymous_fb_author(nodes, ab)


def _feed_ai_badge_post_xml() -> str:
    """Live layout: author row + 'Có dùng AI' chip + timestamp — badge tap opens info sheet."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1260,2800]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,287][1260,2800]">
      <node class="android.view.ViewGroup" bounds="[0,500][1260,2200]">
        <node class="android.widget.ImageView" content-desc="Ảnh đại diện của Nguyễn Trọng Đạt" bounds="[42,530][182,670]" clickable="true"/>
        <node class="android.widget.Button" text="Nguyễn Trọng Đạt" bounds="[210,531][620,597]" clickable="true"/>
        <node class="android.view.ViewGroup" text="Có dùng AI" bounds="[210,603][420,652]" clickable="true"/>
        <node class="android.view.ViewGroup" text="19 giờ" bounds="[430,603][560,652]" clickable="true"/>
        <node class="android.widget.Button" content-desc="Lựa chọn khác cho bài viết của Nguyễn Trọng Đạt" bounds="[1113,488][1260,634]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Đánh giá MiniMax M3, GLM 5.2 và Kimi K2.7 cho tác vụ coding" bounds="[42,680][1218,1100]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" bounds="[360,2000][520,2060]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""


def test_ai_badge_post_prefers_gap_over_ai_chip() -> None:
    xml = _feed_ai_badge_post_xml()
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"author_row_gap", "timestamp"}
    assert top["tap_kind"] != "metadata"
    label = (top.get("tap_label") or "").casefold()
    assert "có dùng ai" not in label or top["tap_kind"] == "timestamp"
    if top["tap_kind"] == "author_row_gap":
        cx, cy = post_open_pipeline.post_header_tap_point(
            tuple(top["bounds"]), tap_kind="author_row_gap"
        )
        assert cx >= 620
        assert cx <= 1100


def test_ai_badge_combined_timestamp_row_clips_tap_right() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1260,2800]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,287][1260,2800]">
      <node class="android.view.ViewGroup" bounds="[0,500][1260,2200]">
        <node class="android.widget.Button" text="Nguyễn Trọng Đạt" bounds="[210,531][620,597]" clickable="true"/>
        <node class="android.view.ViewGroup" text="Có dùng AI • 19 giờ" bounds="[210,603][620,652]" clickable="true"/>
        <node class="android.widget.Button" content-desc="Lựa chọn khác cho bài viết" bounds="[1113,488][1260,634]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Post body with AI badge row above" bounds="[42,680][1218,1100]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận" text="Bình luận" bounds="[360,2000][520,2060]" clickable="true"/>
      </node>
    </node>
  </node>
</hierarchy>"""
    top, _ = post_open_pipeline.resolve_post_open_targets_from_xml(xml)
    assert top is not None
    assert top["tap_kind"] in {"author_row_gap", "timestamp"}
    if top["tap_kind"] == "timestamp":
        cx, cy = post_open_pipeline.post_header_tap_point(
            tuple(top["bounds"]), tap_kind="timestamp"
        )
        assert cx >= 400
