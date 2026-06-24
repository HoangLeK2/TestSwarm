from __future__ import annotations

from relay.extra_data.parsers.facebook.scroll_swipe import (
    hierarchy_has_suggested_groups_block,
    resolve_feed_scroll_swipe_from_xml,
)


def _suggested_groups_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,200][1080,2200]">
      <node class="android.view.ViewGroup" bounds="[0,200][1080,1100]">
        <node text="Thích" bounds="[40,980][200,1040]"/>
      </node>
      <node text="Gợi ý cho bạn" bounds="[40,1180][400,1230]"/>
      <node class="android.widget.HorizontalScrollView" scrollable="true" bounds="[0,1240][1080,1680]">
        <node content-desc="Hội Các Bà Mẹ" bounds="[40,1260][520,1660]"/>
      </node>
      <node text="Tham gia nhóm" bounds="[40,2100][1040,2220]"/>
    </node>
  </node>
</hierarchy>"""


def test_hierarchy_has_suggested_groups_block() -> None:
    xml = _suggested_groups_xml()
    from relay.extra_data.parsers.facebook.parser import _parse_xml

    root = _parse_xml(xml)
    assert root is not None
    assert hierarchy_has_suggested_groups_block(root) is True


def test_resolve_feed_scroll_swipe_avoids_carousel() -> None:
    xml = _suggested_groups_xml()
    swipe = resolve_feed_scroll_swipe_from_xml(
        xml,
        screen_w=1080,
        screen_h=2400,
        start_x_ratio=0.18,
        start_y_ratio=0.65,
        end_y_ratio=0.47,
    )
    assert swipe is not None
    fx, fy, tx, ty = swipe
    assert fx == int(1080 * 0.18)
    assert fy < 1180
    assert ty < fy
    assert fy - ty >= 200


def test_resolve_feed_scroll_swipe_returns_none_without_markers() -> None:
    xml = '<?xml version="1.0"?><hierarchy><node text="hello" bounds="[0,0][100,100]"/></hierarchy>'
    assert resolve_feed_scroll_swipe_from_xml(xml, screen_w=1080, screen_h=2400) is None
