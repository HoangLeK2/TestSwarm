from __future__ import annotations

from tasks.scenario.fb_scroll_swipe import resolve_feed_scroll_swipe_from_xml


def _suggested_groups_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node text="Gợi ý cho bạn" bounds="[40,1180][400,1230]"/>
  <node class="android.widget.HorizontalScrollView" scrollable="true" bounds="[0,1240][1080,1680]"/>
  <node text="Tham gia nhóm" bounds="[40,2100][1040,2220]"/>
</hierarchy>"""


def test_farm_resolve_feed_scroll_swipe_avoids_carousel() -> None:
    swipe = resolve_feed_scroll_swipe_from_xml(
        _suggested_groups_xml(),
        screen_w=1080,
        screen_h=2400,
        start_x_ratio=0.18,
        start_y_ratio=0.65,
        end_y_ratio=0.47,
    )
    assert swipe is not None
    _fx, fy, _tx, ty = swipe
    assert fy < 1180
    assert ty < fy
