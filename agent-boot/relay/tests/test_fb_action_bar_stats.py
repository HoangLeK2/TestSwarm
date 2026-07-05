from __future__ import annotations

from pathlib import Path

from relay.extra_data.parsers.facebook.feed_pipeline import (
    extract_post_comment_count_from_xml,
    parse_fb_count_text,
    parse_fb_posts_from_xml_with_diagnostic,
    resolve_comment_crawl_target,
)
from relay.extra_data.parsers.facebook.comment_pipeline import parse_fb_comments_from_xml_with_diagnostic
from relay.extra_data.parsers.facebook.post_extractor import _extract_post_action_bar_stats
from relay.extra_data.parsers.facebook.parser import _parse_xml
from relay.extra_data.writer import build_content_item_row


ACTION_BAR_SNIPPET = """
<node class="android.view.ViewGroup" clickable="true" bounds="[0,1545][1260,1699]">
  <node class="android.widget.Button" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[0,1545][203,1699]">
    <node text="6" content-desc="6" bounds="[133,1596][161,1650]"/>
  </node>
  <node class="android.widget.Button" content-desc="Bình luận" clickable="true" bounds="[203,1545][430,1699]">
    <node text="23" content-desc="23" bounds="[336,1596][388,1650]"/>
  </node>
  <node class="android.widget.Button" content-desc="Nút Chia sẻ. Nhấn đúp để chia sẻ bài viết." clickable="true" bounds="[430,1545][631,1699]">
    <node text="2" content-desc="2" bounds="[563,1596][589,1650]"/>
  </node>
</node>
"""

ACTION_BAR_NO_COMMENT_COUNT_SNIPPET = """
<node class="android.view.ViewGroup" clickable="true" bounds="[0,1545][1260,1699]">
  <node class="android.widget.Button" content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." clickable="true" bounds="[0,1545][203,1699]">
    <node text="6" content-desc="6" bounds="[133,1596][161,1650]"/>
  </node>
  <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận." text="Bình luận" clickable="true" bounds="[203,1545][430,1699]"/>
  <node class="android.widget.Button" content-desc="Nút Chia sẻ. Nhấn đúp để chia sẻ bài viết." clickable="true" bounds="[430,1545][631,1699]">
    <node text="2" content-desc="2" bounds="[563,1596][589,1650]"/>
  </node>
</node>
"""


def test_extract_post_action_bar_stats_from_snippet() -> None:
    root = _parse_xml(f"<hierarchy>{ACTION_BAR_SNIPPET}</hierarchy>")
    assert root is not None
    stats = _extract_post_action_bar_stats(root)
    assert stats == {"reactions": "6", "comments": "23", "shares": "2"}


def test_extract_post_action_bar_stats_treats_missing_comment_badge_as_unknown() -> None:
    root = _parse_xml(f"<hierarchy>{ACTION_BAR_NO_COMMENT_COUNT_SNIPPET}</hierarchy>")
    assert root is not None
    stats = _extract_post_action_bar_stats(root)
    assert stats == {"reactions": "6", "comments": None, "shares": "2"}


def test_extract_post_action_bar_stats_accepts_loose_accessibility_containers() -> None:
    loose = """
    <node class="android.view.ViewGroup" bounds="[0,2032][1260,2186]">
      <node content-desc="Nút Thích. Hãy nhấn đúp và giữ để bày tỏ cảm xúc về bình luận." bounds="[0,2032][284,2186]">
        <node text="641K" content-desc="641K" bounds="[133,2083][242,2137]"/>
      </node>
      <node content-desc="Bình luận" bounds="[284,2032][585,2186]">
        <node text="60,5K" content-desc="60,5K" bounds="[417,2083][543,2137]"/>
      </node>
      <node content-desc="Nút Chia sẻ. Nhấn đúp để chia sẻ bài viết." bounds="[585,2032][760,2186]">
        <node text="2" content-desc="2" bounds="[650,2083][690,2137]"/>
      </node>
    </node>
    """
    root = _parse_xml(f"<hierarchy>{loose}</hierarchy>")
    assert root is not None
    stats = _extract_post_action_bar_stats(root)
    assert stats == {"reactions": "641K", "comments": "60,5K", "shares": "2"}


def test_capture_hierarchy_la_phu_nhon_post_stats() -> None:
    xml_path = Path(__file__).resolve().parents[3] / (
        "device_farm/captures/10AE7S00HD002JK_2026-05-17_010310/step_000_extract_hierarchy.xml"
    )
    if not xml_path.is_file():
        return
    posts, _ = parse_fb_posts_from_xml_with_diagnostic(xml_path.read_text(), source_index=0)
    la_phu = next((p for p in posts if "La Phu" in (p.get("author") or "")), None)
    assert la_phu is not None
    assert la_phu.get("reactions") == "6"
    assert la_phu.get("comments") == "23"
    assert la_phu.get("shares") == "2"


def test_writer_maps_reactions_comments_shares_to_db_columns() -> None:
    row = build_content_item_row(
        {"author": "A", "text": "body", "reactions": "6", "comments": "23", "shares": "2"},
        {"collection": "test", "hash_scope": "scope-1"},
    )
    assert row["likes_count"] == 6
    assert row["comments_count"] == 23
    assert row["shares_count"] == 2


def test_parse_fb_count_text_handles_suffixes() -> None:
    assert parse_fb_count_text("70") == 70
    assert parse_fb_count_text("1.2K") == 1200
    assert parse_fb_count_text("60,5K") == 60500
    assert parse_fb_count_text("45M") == 45_000_000


def test_resolve_comment_crawl_target_caps_by_post_count() -> None:
    assert resolve_comment_crawl_target(500, 70) == 70
    assert resolve_comment_crawl_target(500, 1000) == 500
    assert resolve_comment_crawl_target(500, 0) == 0
    assert resolve_comment_crawl_target(500, None) == 500


def test_extract_post_comment_count_from_action_bar_snippet() -> None:
    xml = f"<hierarchy>{ACTION_BAR_SNIPPET}</hierarchy>"
    assert extract_post_comment_count_from_xml(xml) == 23


def test_parse_fb_comments_emits_post_stats_from_comment_sheet_action_bar() -> None:
    action_bar = (
        ACTION_BAR_SNIPPET
        .replace('text="6"', 'text="5"')
        .replace('content-desc="6"', 'content-desc="5"')
        .replace('text="23"', 'text="1"')
        .replace('content-desc="23"', 'content-desc="1"')
        .replace('text="2"', 'text="4"')
        .replace('content-desc="2"', 'content-desc="4"')
    )
    xml = f"""
    <hierarchy>
      <node class="android.widget.FrameLayout" package="com.facebook.katana" bounds="[0,0][1260,2800]">
        <node class="androidx.recyclerview.widget.RecyclerView" package="com.facebook.katana" bounds="[0,0][1260,2200]">
          {action_bar}
          <node class="android.widget.Button" package="com.facebook.katana"
            content-desc="Đang hiển thị Tất cả bình luận bình luận. Nhấn để thay đổi bộ lọc bình luận."
            clickable="true" bounds="[40,1720][1220,1810]"/>
        </node>
        <node class="android.widget.AutoCompleteTextView" package="com.facebook.katana"
          text="Viết bình luận công khai..." content-desc="TiniX AI" bounds="[220,2500][980,2600]"/>
      </node>
    </hierarchy>
    """
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id="p1")
    assert diag["reason_code"] == "ok"
    assert diag["comments_returned"] == 0
    assert rows == [{"_type": "post_stats", "reactions": "5", "comments": "1", "shares": "4"}]


def test_extract_post_comment_count_preserves_zero() -> None:
    zero_action_bar = (
        ACTION_BAR_SNIPPET
        .replace('text="23"', 'text="0"')
        .replace('content-desc="23"', 'content-desc="0"')
    )
    xml = f"<hierarchy>{zero_action_bar}</hierarchy>"
    assert extract_post_comment_count_from_xml(xml) == 0


def test_extract_post_comment_count_missing_comment_badge_is_unknown() -> None:
    xml = f"<hierarchy>{ACTION_BAR_NO_COMMENT_COUNT_SNIPPET}</hierarchy>"
    assert extract_post_comment_count_from_xml(xml) is None


def test_extract_post_comment_count_infers_zero_on_comment_sheet_missing_badge() -> None:
    from relay.tests.test_comment_filter import _sheet_xml

    sheet = _sheet_xml().replace(
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
        f"{ACTION_BAR_NO_COMMENT_COUNT_SNIPPET}"
        '<node package="com.facebook.katana" clickable="true" bounds="[40,180][680,260]"',
    )
    assert extract_post_comment_count_from_xml(sheet) == 0


def test_extract_post_comment_count_no_comments_text_without_count_is_unknown() -> None:
    xml = (
        f"<hierarchy>{ACTION_BAR_NO_COMMENT_COUNT_SNIPPET}"
        '<node class="android.widget.TextView" text="Chưa có bình luận nào" />'
        "</hierarchy>"
    )
    assert extract_post_comment_count_from_xml(xml) is None


def test_extract_post_comment_count_prefers_positive_header_over_missing_badge_zero() -> None:
    xml = (
        f"<hierarchy>{ACTION_BAR_NO_COMMENT_COUNT_SNIPPET}"
        '<node class="android.widget.TextView" text="23 bình luận" '
        'content-desc="23 bình luận" bounds="[40,380][300,420]" />'
        "</hierarchy>"
    )
    assert extract_post_comment_count_from_xml(xml) == 23
