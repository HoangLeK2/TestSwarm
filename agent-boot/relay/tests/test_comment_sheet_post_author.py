from __future__ import annotations

from pathlib import Path

from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vivo_comment_sheet_kent_juno_post.xml"


def test_comment_sheet_post_author_is_poster_not_group_name() -> None:
    xml = _FIXTURE.read_text(encoding="utf-8")
    posts, diag = parse_fb_posts_from_xml_with_diagnostic(xml)
    assert diag["reason_code"] == "ok"
    assert len(posts) == 1
    post = posts[0]
    assert post["author"] == "Kent Juno"
    assert post["timestamp"] == "1 ngày•Chia sẻ với: Nhóm công khai"
    assert "openclaw vn" not in post["author"].lower()
    assert post.get("badges") == ["Người đóng góp nhiều nhất"]


def test_feed_post_contributor_badge_not_author() -> None:
    """Regression: HyperX-style badge row must not replace poster name."""
    from relay.extra_data.parsers.facebook.feed_pipeline import (
        parse_fb_posts_from_xml_with_diagnostic,
    )

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1260,2800]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,287][1260,2800]">
      <node class="android.view.ViewGroup" bounds="[0,800][1260,2000]">
        <node class="android.widget.Button" text="HyperX" bounds="[210,842][420,898]" clickable="true"/>
        <node class="android.view.ViewGroup" text="★ Người đóng góp đáng tin • 6 giờ" bounds="[210,910][900,960]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Trình Chỉnh Sửa Video AI" bounds="[42,1020][1218,1700]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Bình luận" clickable="true" bounds="[154,1700][308,1850]"/>
      </node>
    </node>
  </node>
</hierarchy>"""
    posts, diag = parse_fb_posts_from_xml_with_diagnostic(xml)
    assert diag["reason_code"] == "ok"
    assert len(posts) == 1
    post = posts[0]
    assert post["author"] == "HyperX"
    assert post["timestamp"] == "6 giờ"
    assert post.get("badges") == ["★ Người đóng góp đáng tin"]
    assert "Trình Chỉnh Sửa Video AI" in post["text"]
