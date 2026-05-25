from __future__ import annotations

from pathlib import Path

from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic
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


def test_extract_post_action_bar_stats_from_snippet() -> None:
    root = _parse_xml(f"<hierarchy>{ACTION_BAR_SNIPPET}</hierarchy>")
    assert root is not None
    stats = _extract_post_action_bar_stats(root)
    assert stats == {"reactions": "6", "comments": "23", "shares": "2"}


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
