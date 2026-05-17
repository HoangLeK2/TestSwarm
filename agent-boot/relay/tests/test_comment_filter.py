from __future__ import annotations

from relay.extra_data.ingest import _parse_items
from relay.extra_data.parsers.facebook.comment_filter import (
    _is_already_on_filter,
    _is_sort_bottom_sheet_open,
    normalize_comment_filter,
    resolve_comment_filter_next_tap,
)


def _sheet_xml(
    *,
    open_sort: bool = False,
    current_filter: str = "most_relevant",
) -> str:
    filter_rows = {
        "most_relevant": (
            '<node clickable="true" bounds="[40,180][680,260]" '
            'content-desc="Đang hiển thị Phù hợp nhất bình luận. Nhấn để thay đổi bộ lọc bình luận." />'
        ),
        "newest": (
            '<node clickable="true" bounds="[40,180][680,260]" '
            'content-desc="Đang hiển thị Mới nhất bình luận. Nhấn để thay đổi bộ lọc bình luận." />'
        ),
        "all_comments": (
            '<node clickable="true" bounds="[40,180][680,260]" '
            'content-desc="Đang hiển thị Tất cả bình luận. Nhấn để thay đổi bộ lọc bình luận." />'
        ),
    }
    filter_row = filter_rows[current_filter]
    sort_nodes = ""
    if open_sort:
        sort_nodes = """
        <node text="Phù hợp nhất" clickable="true" bounds="[40,900][680,980]" />
        <node text="Hiển thị bình luận của bạn bè" bounds="[40,980][680,1020]" />
        <node text="Mới nhất" clickable="true" bounds="[40,1040][680,1120]" />
        <node text="Hiển thị tất cả bình luận, mới nhất trước tiên." bounds="[40,1120][680,1160]" />
        <node text="Tất cả bình luận" clickable="true" bounds="[40,1180][680,1260]" />
        <node text="Hiển thị tất cả bình luận, bao gồm cả nội dung có thể là spam." bounds="[40,1260][680,1320]" />
        """
    pkg = 'package="com.facebook.katana"'
    return f"""<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][720,1600]" {pkg}>
    <node class="android.widget.Button" text="Đóng" content-desc="Đóng" bounds="[0,40][120,120]" {pkg} />
    <node class="android.widget.AutoCompleteTextView" text="Viết bình luận công khai…" bounds="[40,1400][680,1500]" {pkg} />
    {filter_row.replace("<node", f"<node {pkg}")}
    <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,200][720,1550]" {pkg}>
      <node class="android.view.ViewGroup" bounds="[0,300][720,900]" {pkg} />
    </node>
    {sort_nodes.replace('<node', f'<node {pkg}')}
  </node>
</hierarchy>"""


def test_sort_bottom_sheet_detection() -> None:
    root_xml = _sheet_xml(open_sort=True)
    from relay.extra_data.parsers.facebook.parser import _parse_xml

    root = _parse_xml(root_xml)
    assert root is not None
    assert _is_sort_bottom_sheet_open(root) is True


def test_open_sheet_tap_targets_filter_indicator_not_spam_description() -> None:
    plan = resolve_comment_filter_next_tap(
        _sheet_xml(),
        {"comment_filter": "all_comments"},
    )
    assert plan["phase"] == "open_sheet"
    assert plan["tap"]["bounds"][1] < 300


def test_select_all_tap_targets_title_row_not_description() -> None:
    plan = resolve_comment_filter_next_tap(
        _sheet_xml(open_sort=True),
        {"comment_filter": "all_comments"},
    )
    assert plan["phase"] == "select_option"
    assert plan["tap"]["bounds"][1] >= 1180
    assert plan["tap"]["bounds"][3] <= 1280


def test_select_newest_tap_targets_title_row() -> None:
    plan = resolve_comment_filter_next_tap(
        _sheet_xml(open_sort=True),
        {"comment_filter": "newest"},
    )
    assert plan["phase"] == "select_option"
    assert plan["target_filter"] == "newest"
    assert 1040 <= plan["tap"]["bounds"][1] <= 1120


def test_already_on_filter_skips_tap() -> None:
    plan = resolve_comment_filter_next_tap(
        _sheet_xml(current_filter="all_comments"),
        {"comment_filter": "all_comments"},
    )
    assert plan["phase"] == "done"
    assert plan["reason_code"] == "already_on_filter"


def test_normalize_legacy_switch_off() -> None:
    assert normalize_comment_filter(None, switch_to_all_comments=False) is None
    assert normalize_comment_filter(None, switch_to_all_comments=True) == "all_comments"


def test_ingest_fb_comment_filter_next_strategy() -> None:
    _, diagnostic = _parse_items(
        "fb_comment_filter_next",
        _sheet_xml(open_sort=True),
        {"comment_filter": "all_comments"},
    )
    assert diagnostic["phase"] == "select_option"
    assert diagnostic["tap"]["bounds"]


def test_already_most_relevant() -> None:
    root_xml = _sheet_xml(current_filter="most_relevant")
    from relay.extra_data.parsers.facebook.parser import _parse_xml

    root = _parse_xml(root_xml)
    assert root is not None
    assert _is_already_on_filter(root, "most_relevant") is True
