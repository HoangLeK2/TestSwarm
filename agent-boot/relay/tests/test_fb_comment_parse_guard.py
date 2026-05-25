from __future__ import annotations

from relay.extra_data.parsers.facebook.comment_pipeline import parse_fb_comments_from_xml_with_diagnostic
from relay.extra_data.parsers.facebook.filters import (
    _is_feed_comment_preview_chrome,
    _is_junk_parsed_comment_row,
)


def test_feed_preview_chrome_detected() -> None:
    assert _is_feed_comment_preview_chrome("Xem 2 câu trả lời")
    assert _is_feed_comment_preview_chrome("Xem 1 câu trả lời cho Quang Đạo…")
    assert _is_feed_comment_preview_chrome(
        "Các bình luận đã bị ẩn do có thể mang tính xúc phạm"
    )
    assert not _is_feed_comment_preview_chrome("Này bữa mình bị rồi k bik bác giống mình k")


def test_junk_row_rejects_author_only() -> None:
    assert _is_junk_parsed_comment_row({"author": "Quang Đạo", "text": ""})


def test_parse_comments_requires_comment_sheet() -> None:
    feed_xml = """<?xml version="1.0"?>
<hierarchy>
  <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,2400]">
    <node bounds="[0,300][1080,800]">
      <node text="Xem 2 câu trả lời" bounds="[200,700][900,750]" />
      <node text="Bình luận" bounds="[100,760][300,800]" class="android.widget.Button" />
    </node>
  </node>
</hierarchy>"""
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(feed_xml, parent_post_id="p1")
    assert rows == []
    assert diag["reason_code"] == "not_comment_sheet"
