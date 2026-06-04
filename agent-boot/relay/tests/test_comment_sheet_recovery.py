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


def test_no_interrupt_when_sort_bottom_sheet_open() -> None:
    assert detect_comment_sheet_interrupt_from_xml(_sheet_xml(open_sort=True)) is None


def test_interrupt_reason_allows_back_only_for_keyboard() -> None:
    from relay.extra_data.parsers.facebook.comment_pipeline import interrupt_reason_allows_back

    assert interrupt_reason_allows_back("keyboard_open") is True
    assert interrupt_reason_allows_back("left_comment_sheet") is False
    assert interrupt_reason_allows_back(None) is False


def test_interrupt_reason_never_back_when_group_navigation_locked() -> None:
    from relay.extra_data.parsers.facebook.comment_pipeline import interrupt_reason_allows_back

    ctx = {"_fb_group_navigation": True}
    assert interrupt_reason_allows_back("keyboard_open", ctx) is False


def test_context_implies_fb_group_from_collection() -> None:
    from relay.extra_data.parsers.facebook.comment_pipeline import (
        context_implies_fb_group_navigation,
        note_fb_group_navigation,
    )

    ctx = {"collection": "fb_group_posts"}
    assert context_implies_fb_group_navigation(ctx) is True
    note_fb_group_navigation(ctx)
    assert ctx["_fb_group_navigation"] is True


def test_should_not_back_from_group_feed_after_failed_tap() -> None:
    from relay.extra_data.parsers.facebook.comment_pipeline import (
        is_group_feed_from_xml,
        should_press_back_after_failed_tap,
    )

    feed_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" text="Bạn viết gì đi…" bounds="[40,200][900,280]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,300][1080,2200]" />
</hierarchy>"""
    assert is_group_feed_from_xml(feed_xml) is True
    assert should_press_back_after_failed_tap(feed_xml) is False


def test_should_back_from_profile_overlay() -> None:
    from relay.extra_data.parsers.facebook.comment_pipeline import should_press_back_after_failed_tap

    profile_xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" text="Trang cá nhân" bounds="[40,200][400,260]" />
</hierarchy>"""
    assert should_press_back_after_failed_tap(profile_xml) is True


def test_comment_sheet_avatar_desc_is_not_profile_overlay() -> None:
    from pathlib import Path

    from relay.extra_data.parsers.facebook.comment_pipeline import (
        should_press_back_after_failed_tap,
    )

    path = (
        Path(__file__).resolve().parents[2]
        / "debug"
        / "traces"
        / "walk_reports"
        / "r1_comments.xml"
    )
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    assert should_press_back_after_failed_tap(xml) is False


def test_feed_avatar_desc_is_not_profile_overlay() -> None:
    """Regression: feed cards must not trigger BACK via ảnh đại diện avatar chrome."""
    from pathlib import Path

    from relay.extra_data.parsers.facebook.comment_pipeline import (
        should_press_back_after_failed_tap,
    )

    path = (
        Path(__file__).resolve().parents[2]
        / "debug"
        / "traces"
        / "walk_reports"
        / "mcp_screen_group_feed.xml"
    )
    if not path.is_file():
        return
    xml = path.read_text(encoding="utf-8")
    assert should_press_back_after_failed_tap(xml) is False


def test_comment_tap_point_biases_right() -> None:
    from relay.extra_data.parsers.facebook.comment_pipeline import comment_tap_point

    cx, cy = comment_tap_point((400, 1000, 700, 1050), screen_w=1080)
    assert cx >= 520
    assert cy == 1025
