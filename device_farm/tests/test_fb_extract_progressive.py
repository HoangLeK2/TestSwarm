"""Unit tests for progressive 'See more' expansion in fb_extract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch

from tasks.fb_extract import _expand_see_more, _dedup


def _xml_with_clickables(*, texts: List[str] | None = None, descs: List[str] | None = None) -> str:
    texts = texts or []
    descs = descs or []
    nodes: List[str] = []
    y = 300
    for t in texts:
        nodes.append(
            f'<node class="android.widget.Button" clickable="true" text="{t}" '
            f'content-desc="" bounds="[100,{y}][500,{y + 80}]"/>'
        )
        y += 120
    for d in descs:
        nodes.append(
            f'<node class="android.widget.Button" clickable="true" text="" '
            f'content-desc="{d}" bounds="[100,{y}][500,{y + 80}]"/>'
        )
        y += 120
    body = "\n".join(nodes) if nodes else '<node class="android.widget.TextView" text="noop" bounds="[0,300][100,340]"/>'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
{body}
</hierarchy>"""


@dataclass
class _FakeDevice:
    xml_sequence: List[str]
    xml_calls: int = 0
    taps: List[tuple[int, int]] = field(default_factory=list)
    scrolls: List[tuple[str, float]] = field(default_factory=list)

    def hierarchy_xml(self, force_refresh: bool = True) -> str:
        idx = min(self.xml_calls, len(self.xml_sequence) - 1)
        self.xml_calls += 1
        return self.xml_sequence[idx]

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def scroll(self, direction: str, distance: float) -> None:
        self.scrolls.append((direction, distance))


def test_expand_see_more_progressive_long_post_multi_stage():
    """Simulate long post that reveals more 'Xem thêm' in multiple stages."""
    device = _FakeDevice(
        xml_sequence=[
            _xml_with_clickables(texts=["Xem thêm"]),  # pass 1
            _xml_with_clickables(texts=["Xem thêm"]),  # pass 2 after scroll
            _xml_with_clickables(),                    # pass 3 no candidate
            _xml_with_clickables(),                    # pass 4 no candidate -> stop
        ]
    )

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(
            device,
            max_passes=6,
            scroll_between=True,
            scroll_distance=0.22,
            no_change_threshold=2,
        )

    assert expanded == 2
    assert len(device.taps) == 2
    assert any(d == ("down", 0.22) for d in device.scrolls)


def test_expand_see_more_supports_content_desc_candidates():
    """Facebook sometimes exposes labels via content-desc instead of text."""
    device = _FakeDevice(
        xml_sequence=[
            _xml_with_clickables(descs=["Xem thêm"]),
            _xml_with_clickables(),
        ]
    )

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(device, max_passes=2, scroll_between=False)

    assert expanded == 1
    assert len(device.taps) == 1


def test_expand_see_more_supports_comment_pagination_labels():
    """Should also tap 'xem thêm bình luận/câu trả lời' labels."""
    device = _FakeDevice(
        xml_sequence=[
            _xml_with_clickables(texts=["Xem thêm bình luận", "Xem thêm câu trả lời"]),
            _xml_with_clickables(),
        ]
    )

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(device, max_passes=2, scroll_between=False)

    assert expanded == 2
    assert len(device.taps) == 2


def test_expand_see_more_respects_max_total_taps_limit():
    """Guard against over-tapping when many expandable nodes are present."""
    device = _FakeDevice(
        xml_sequence=[
            _xml_with_clickables(texts=["Xem thêm", "Xem thêm", "Xem thêm"]),
            _xml_with_clickables(texts=["Xem thêm", "Xem thêm", "Xem thêm"]),
        ]
    )

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(
            device,
            max_passes=5,
            max_total_taps=4,
            scroll_between=False,
        )

    assert expanded == 4
    assert len(device.taps) == 4


def test_expand_see_more_taps_clickable_ancestor_when_label_not_clickable():
    """FB can render 'Xem thêm' as non-clickable child under clickable parent."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.view.ViewGroup" clickable="true" bounds="[100,300][500,380]">
    <node class="android.widget.TextView" clickable="false" text="Xem thêm" content-desc="" bounds="[120,320][260,350]"/>
  </node>
</hierarchy>"""
    device = _FakeDevice(xml_sequence=[xml, _xml_with_clickables()])

    with patch("tasks.fb_extract.time.sleep", return_value=None):
        expanded = _expand_see_more(device, max_passes=2, scroll_between=False)

    assert expanded == 1
    assert len(device.taps) == 1
    # Tap should target parent clickable container center: (300, 340)
    assert device.taps[0] == (300, 340)


def test_dedup_prefers_expanded_post_over_truncated_preview():
    truncated = {
        "author": "Huyền Lê",
        "timestamp": "1 ngày",
        "text": "Mình vừa thử cách host OpenClaw mới và nó giải quyết đúng cái đau đầu nhất của mình.… Xem thêm",
        "reactions": None,
        "comments": None,
        "shares": None,
        "views": None,
        "image_desc": None,
        "comment_preview": None,
    }
    expanded = {
        "author": "Huyền Lê",
        "timestamp": "1 ngày",
        "text": (
            "Mình vừa thử cách host OpenClaw mới và nó giải quyết đúng cái đau đầu nhất của mình. "
            "Đầu tiên là setup nhanh, sau đó ổn định hơn khi chạy dài. "
            "Nếu ai đang gặp vấn đề timeout thì nên thử GreenNode."
        ),
        "reactions": "12",
        "comments": "3",
        "shares": None,
        "views": None,
        "image_desc": "Ảnh",
        "comment_preview": None,
    }

    out = _dedup([truncated, expanded])
    assert len(out) == 1
    assert "Xem thêm" not in out[0]["text"]
    assert len(out[0]["text"]) > len(truncated["text"])


def test_dedup_stable_post_id_ignores_timestamp_variation():
    p1 = {
        "author": "A",
        "timestamp": "1 giờ",
        "text": "Nội dung rất dài đã bung full",
        "stable_post_id": "sid",
        "post_key": "k1",
    }
    p2 = {
        "author": "A",
        "timestamp": "59 phút",
        "text": "Nội dung rất dài đã bung full",
        "stable_post_id": "sid",
        "post_key": "k2",
    }
    out = _dedup([p1, p2])
    assert len(out) == 1


def test_dedup_keeps_distinct_posts_when_stable_id_collides():
    p1 = {
        "author": "A",
        "timestamp": "1 giờ",
        "text": "Bài thứ nhất mở đầu giống nhau nhưng phần sau khác hẳn",
        "stable_post_id": "same-sid",
        "post_key": "k1",
    }
    p2 = {
        "author": "A",
        "timestamp": "2 giờ",
        "text": "Bài thứ hai mở đầu giống nhau nhưng nội dung về chủ đề hoàn toàn khác",
        "stable_post_id": "same-sid",
        "post_key": "k2",
    }
    out = _dedup([p1, p2])
    assert len(out) == 2
