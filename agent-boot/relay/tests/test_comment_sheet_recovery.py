from __future__ import annotations

from relay.extra_data.parsers.facebook.comment_pipeline import (
    detect_comment_sheet_interrupt_from_xml,
    resolve_comment_scroll_swipe_from_xml,
)
from relay.extra_data.parsers.facebook.parser import _parse_xml
from relay.tests.test_comment_filter import _sheet_xml


def test_swipe_avoids_left_avatar_column() -> None:
    swipe = resolve_comment_scroll_swipe_from_xml(_sheet_xml(), distance_ratio=0.5)
    assert swipe is not None
    fx, _fy, _tx, _ty = swipe
    assert fx >= 400


def test_detect_keyboard_from_focused_composer() -> None:
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" text="Phù hợp nhất" bounds="[40,450][400,500]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2200]" />
  <node package="com.facebook.katana" class="android.widget.EditText"
        focused="true" text="Viết bình luận…" bounds="[40,2280][1040,2340]" />
</hierarchy>"""
    assert detect_comment_sheet_interrupt_from_xml(xml) == "keyboard_open"


def test_detect_left_sheet_when_not_comment_ui() -> None:
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" text="Trang cá nhân" bounds="[40,200][400,260]" />
</hierarchy>"""
    assert detect_comment_sheet_interrupt_from_xml(xml) == "left_comment_sheet"


def test_no_interrupt_on_normal_sheet() -> None:
    assert detect_comment_sheet_interrupt_from_xml(_sheet_xml()) is None
