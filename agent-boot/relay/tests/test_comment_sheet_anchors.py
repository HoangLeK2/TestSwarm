from __future__ import annotations

from lxml import etree

from relay.extra_data.parsers.facebook.comment_pipeline import (
    _node_has_comment_button_token,
    _resolve_comment_sheet_anchors,
    parse_fb_comments_from_xml_with_diagnostic,
)


def test_stat_row_count_is_not_comment_button() -> None:
    stat = etree.fromstring(
        '<node class="android.widget.TextView" text="23 bình luận" '
        'bounds="[40,520][300,560]" />'
    )
    assert not _node_has_comment_button_token(stat)


def test_action_bar_count_badge_can_be_comment_button() -> None:
    btn = etree.fromstring(
        '<node class="android.widget.Button" clickable="true" '
        'content-desc="23 bình luận" bounds="[220,1100][380,1160]" />'
    )
    assert _node_has_comment_button_token(btn)


def test_comment_sheet_anchors_use_filter_and_composer() -> None:
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" text="Phù hợp nhất" bounds="[40,450][400,500]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2200]">
    <node bounds="[0,500][1080,700]">
      <node text="Lê Bách" bounds="[40,520][300,560]" />
      <node text="Vừa cho con gpt check" bounds="[40,560][1000,620]" />
    </node>
    <node bounds="[0,720][1080,900]">
      <node text="Nguyễn A" bounds="[40,740][300,780]" />
      <node text="Comment body one" bounds="[40,780][1000,840]" />
    </node>
  </node>
  <node package="com.facebook.katana" class="android.widget.EditText"
        text="Viết bình luận…" bounds="[40,2280][1040,2340]" />
</hierarchy>"""
    from relay.extra_data.parsers.facebook.parser import _parse_xml

    root = _parse_xml(xml)
    assert root is not None
    y2, _mid, y_max = _resolve_comment_sheet_anchors(root)
    assert y2 is not None and y2 >= 500
    assert y_max is not None and y_max <= 2280


def test_parse_includes_comment_body_in_left_column() -> None:
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" text="Phù hợp nhất" bounds="[40,450][400,500]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2200]">
    <node bounds="[0,720][1080,900]">
      <node text="Nguyễn A" bounds="[56,740][140,780]" />
      <node text="Nội dung cột trái" bounds="[72,780][1000,840]" />
    </node>
  </node>
  <node package="com.facebook.katana" text="Viết bình luận…" bounds="[40,2280][1040,2340]" />
</hierarchy>"""
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id="p1")
    assert diag["reason_code"] == "ok"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert any(r.get("text") == "Nội dung cột trái" for r in bodies)


def test_parse_comments_on_sheet_excludes_header_stats() -> None:
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" text="23 bình luận" bounds="[40,380][300,420]" />
  <node package="com.facebook.katana" text="Phù hợp nhất" bounds="[40,450][400,500]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2200]">
    <node bounds="[0,720][1080,900]">
      <node text="Nguyễn A" bounds="[180,740][300,780]" />
      <node text="Đúng bài này" bounds="[180,780][1000,840]" />
    </node>
  </node>
  <node package="com.facebook.katana" text="Viết bình luận…" bounds="[40,2280][1040,2340]" />
</hierarchy>"""
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id="p1")
    assert diag["reason_code"] == "ok"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert any(r.get("text") == "Đúng bài này" for r in bodies)
    assert not any(r.get("text") == "23 bình luận" for r in bodies)


def test_parse_comments_on_sheet_excludes_parent_post_body_anchor() -> None:
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" text="Phù hợp nhất" bounds="[40,450][400,500]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2200]">
    <node bounds="[0,520][1080,720]">
      <node text="Vũ Nguyễn Thiên Ân" bounds="[78,540][560,585]" />
      <node text="Mình đang dùng gói 20x và sau ... xem thêm Ảnh" bounds="[78,600][1000,660]" />
    </node>
    <node bounds="[0,780][1080,960]">
      <node text="Nguyễn A" bounds="[78,800][300,840]" />
      <node text="Comment thật trong bài" bounds="[78,850][1000,910]" />
    </node>
  </node>
  <node package="com.facebook.katana" text="Viết bình luận…" bounds="[40,2280][1040,2340]" />
</hierarchy>"""
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(
        xml,
        parent_post_id="p1",
        parent_post_anchor={
            "author": "Vũ Nguyễn Thiên Ân",
            "text_prefix": "Mình đang dùng gói 20x và sau",
        },
    )
    assert diag["reason_code"] == "ok"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert [r.get("text") for r in bodies] == ["Comment thật trong bài"]
