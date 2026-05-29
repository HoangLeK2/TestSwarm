from __future__ import annotations

from relay.extra_data.parsers.facebook.parser import _hierarchy_is_fb_comment_sheet, _parse_xml


def test_comment_sheet_detected_with_sort_row_no_close_label() -> None:
    """Matches group comment UI: Phù hợp nhất + list, icon back only (no Đóng text)."""
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="android.widget.Button"
        clickable="true" content-desc="Quay lại" bounds="[0,80][120,160]" />
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,400][1080,2350]">
    <node bounds="[0,420][1080,900]">
      <node text="Phù hợp nhất" bounds="[40,450][400,500]" />
      <node text="Lê Bách" bounds="[40,520][300,560]" />
      <node text="Vừa cho con gpt check" bounds="[40,560][1000,620]" />
    </node>
  </node>
</hierarchy>"""
    root = _parse_xml(xml)
    assert root is not None
    assert _hierarchy_is_fb_comment_sheet(root) is True


def test_group_feed_with_phu_hop_nhat_is_not_comment_sheet() -> None:
    """Group feed also has Phù hợp nhất sort — must not confuse with comment sheet."""
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,200][1080,2400]">
    <node bounds="[0,300][1080,500]">
      <node text="OpenClaw VN" bounds="[40,320][400,360]" />
    </node>
    <node bounds="[0,600][1080,900]">
      <node text="Bạn viết gì đi..." bounds="[40,620][500,680]" />
      <node text="Phù hợp nhất" bounds="[40,700][300,750]" />
      <node text="Jang Jang" bounds="[40,780][300,820]" />
    </node>
  </node>
</hierarchy>"""
    root = _parse_xml(xml)
    assert root is not None
    assert _hierarchy_is_fb_comment_sheet(root) is False


def test_feed_with_comment_button_is_not_comment_sheet() -> None:
    xml = """<?xml version="1.0"?>
<hierarchy bounds="[0,0][1080,2400]">
  <node package="com.facebook.katana" class="androidx.recyclerview.widget.RecyclerView"
        scrollable="true" bounds="[0,200][1080,2400]">
    <node bounds="[0,300][1080,1200]">
      <node class="android.view.ViewGroup" clickable="true" bounds="[40,1100][200,1160]">
        <node text="Bình luận" clickable="false" bounds="[50,1110][150,1140]" />
      </node>
    </node>
  </node>
</hierarchy>"""
    root = _parse_xml(xml)
    assert root is not None
    assert _hierarchy_is_fb_comment_sheet(root) is False
