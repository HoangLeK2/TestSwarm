"""Tests for relay.u2_executor — batch executor + primitive ops."""
from __future__ import annotations

import asyncio
import base64
import io
import threading
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

import relay.u2_executor as u2_exec_mod
from relay.u2_executor import U2Executor, _resolve
from relay.u2_session_pool import U2SessionPool


@pytest.fixture
def mock_device():
    dev = MagicMock()
    return dev


@pytest.fixture
def executor(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.get_session = AsyncMock(return_value=mock_device)
    pool.evict = AsyncMock()
    exc = U2Executor(pool=pool, loop=event_loop)
    return exc, mock_device, pool


class _FlowDevice:
    def __init__(self, *hierarchies: str) -> None:
        self._hierarchies = list(hierarchies)
        self.clicks: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int, float]] = []
        self.advance_on_click = False

    def dump_hierarchy(self, compressed: bool = False) -> str:
        assert compressed is False
        if len(self._hierarchies) > 1:
            return self._hierarchies.pop(0)
        return self._hierarchies[0]

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))
        if self.advance_on_click and len(self._hierarchies) > 1:
            self._hierarchies.pop(0)

    def swipe(
        self,
        fx: int,
        fy: int,
        tx: int,
        ty: int,
        duration: float = 0.5,
    ) -> None:
        self.swipes.append((fx, fy, tx, ty, duration))

    def window_size(self) -> tuple[int, int]:
        return (1080, 2400)


def _fb_xml(*nodes: str) -> str:
    return f"<hierarchy>{''.join(nodes)}</hierarchy>"


def _fb_node(
    label: str,
    *,
    bounds: str,
    clickable: bool = False,
) -> str:
    return (
        f'<node text="{label}" content-desc="{label}" '
        f'clickable="{str(clickable).lower()}" bounds="{bounds}" />'
    )


def test_flow_fb_connect_visible_people_clicks_only_common_context_row(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    after = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("Hủy lời mời", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before, after)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "min_score": 40,
            "require_common": True,
            "common_keywords": ["bạn chung", "cùng nhóm"],
        },
    )

    assert result["verified"] is True
    assert result["source"] == "visible_people_surface"
    assert result["target_id"].startswith("ui:")
    assert "ban chung" in result["matched_common"]
    assert result["selected_tap"] == [750, 160]
    assert dev.clicks == [(750, 160)]


def test_flow_fb_connect_visible_people_does_not_click_without_common_context():
    before = _fb_xml(
        _fb_node("Random Name", bounds="[40,100][400,145]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"min_score": 40, "require_common": True},
    )

    assert result["verified"] is False
    assert result["reason"] == "no_common_connectable_people"
    assert dev.clicks == []


def test_flow_fb_connect_visible_people_batch_sends_multiple_common_rows(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
        _fb_node("No Mutual", bounds="[40,540][400,585]"),
        _fb_node("Thêm bạn bè", bounds="[600,560][900,640]", clickable=True),
    )
    after_a = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("Hủy lời mời", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
    )
    after_b = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("Hủy lời mời", bounds="[600,340][900,420]", clickable=True),
    )
    # after_a appears twice: once as the post-tap verification read, once as the
    # re-aim read before tapping the second row. Sending a request removes the
    # first card on a real device, so coordinates captured before that must be
    # re-confirmed rather than reused.
    dev = _FlowDevice(before, after_a, after_a, after_b)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is True
    assert result["batch"] is True
    assert result["sent_count"] == 2
    assert [item["mutual_count"] for item in result["sent"]] == [3, 1]
    assert dev.clicks == [(750, 160), (750, 380)]


def test_flow_fb_connect_visible_people_batch_dry_run_does_not_click(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
    )
    dev = _FlowDevice(before)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 0,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is False
    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 2
    assert result["sent_count"] == 0
    assert dev.clicks == []


def test_flow_fb_connect_visible_people_dedupes_same_person_after_scroll(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    first_screen = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Cu Minh", bounds="[40,100][400,145]"),
        _fb_node("1 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    overlapped_scroll = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Cu Minh", bounds="[40,260][400,305]"),
        _fb_node("1 bạn chung", bounds="[40,306][400,350]"),
        _fb_node("Bạn bè Bạn bè", bounds="[40,351][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,280][900,360]", clickable=True),
    )
    dev = _FlowDevice(first_screen, overlapped_scroll)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 1,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 1
    assert [item["display_name"] for item in result["eligible"]] == ["Cu Minh"]
    assert dev.clicks == []


def test_flow_fb_connect_visible_people_stops_after_unverified_tap(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Tran Van B", bounds="[40,320][400,365]"),
        _fb_node("1 bạn chung", bounds="[40,366][400,410]"),
        _fb_node("Thêm bạn bè", bounds="[600,340][900,420]", clickable=True),
    )
    unchanged_after_tap = before
    dev = _FlowDevice(before, unchanged_after_tap)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 2,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is False
    assert result["reason"] == "request_not_verified"
    assert result["sent_count"] == 0
    assert result["eligible_count"] == 1
    assert len(result["skipped"]) == 1
    assert dev.clicks == [(750, 160)]


def test_flow_fb_connect_visible_people_accepts_same_group_only_context(monkeypatch):
    """Cold start: an account with no friends has no mutuals, only shared groups."""
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Le Thi C", bounds="[40,100][400,145]"),
        _fb_node("Cùng nhóm Hội Yêu Bếp", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    after = _fb_xml(
        _fb_node("Le Thi C", bounds="[40,100][400,145]"),
        _fb_node("Hủy lời mời", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before, after)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"target_count": 1, "max_scrolls": 0, "min_score": 40, "require_common": True},
    )

    assert result["verified"] is True
    assert result["sent_count"] == 1
    assert "cung nhom" in result["sent"][0]["matched_common"]


def test_flow_fb_connect_visible_people_keeps_person_named_trang(monkeypatch):
    """"Trang" is a given name, not evidence of a Page."""
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Nguyen Thuy Trang", bounds="[40,100][400,145]"),
        _fb_node("2 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    after = _fb_xml(
        _fb_node("Nguyen Thuy Trang", bounds="[40,100][400,145]"),
        _fb_node("Đã gửi lời mời", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before, after)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"target_count": 1, "max_scrolls": 0, "min_score": 40, "require_common": True},
    )

    assert result["verified"] is True
    assert result["sent"][0]["display_name"] == "Nguyen Thuy Trang"


def test_flow_fb_connect_visible_people_keeps_row_with_follow_button(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Pham Van D", bounds="[40,100][400,145]"),
        _fb_node("5 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Theo dõi", bounds="[420,120][560,200]", clickable=True),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    after = _fb_xml(_fb_node("Pham Van D", bounds="[40,100][400,145]"))
    dev = _FlowDevice(before, after)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"target_count": 1, "max_scrolls": 0, "min_score": 40, "require_common": True},
    )

    assert result["verified"] is True
    assert result["sent_count"] == 1


def test_flow_fb_connect_visible_people_counts_removed_row_as_sent(monkeypatch):
    """Facebook drops the suggestion once the request lands — that is a success."""
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Vo Thi E", bounds="[40,100][400,145]"),
        _fb_node("4 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    after = _fb_xml(_fb_node("Gợi ý khác", bounds="[40,900][400,945]"))
    dev = _FlowDevice(before, after)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"target_count": 1, "max_scrolls": 0, "min_score": 40, "require_common": True},
    )

    assert result["verified"] is True
    assert result["sent_count"] == 1
    assert result["skipped"] == []


def test_flow_fb_connect_visible_people_reports_why_rows_were_dropped():
    """A cold account must be able to tell "no context" from "token mismatch"."""
    before = _fb_xml(
        _fb_node("Hoang Van F", bounds="[40,100][400,145]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"target_count": 1, "max_scrolls": 0, "min_score": 40, "require_common": True},
    )

    assert result["sent_count"] == 0
    assert result["reason"] == "no_common_connectable_people"
    reasons = [item["reason"] for item in result["rejected"]]
    assert "no_common_context" in reasons
    assert "Hoang Van F" in result["rejected"][0]["row_text"]


def test_flow_fb_connect_visible_people_reports_below_min_score_rows():
    before = _fb_xml(
        _fb_node("Dang Van G", bounds="[40,100][400,145]"),
        _fb_node("Sống tại Hà Nội", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(before)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 1,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
            "common_keywords": ["sống tại"],
        },
    )

    assert result["sent_count"] == 0
    dropped = [item for item in result["rejected"] if item["reason"] == "below_min_score"]
    assert dropped and dropped[0]["score"] == 20


def test_flow_fb_connect_visible_people_opens_find_friends_surface(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    home = _fb_xml(_fb_node("Menu", bounds="[40,180][140,260]"))
    menu = _fb_xml(
        _fb_node("Menu", bounds="[20,20][200,80]"),
        _fb_node("Xem thêm", bounds="[70,900][440,980]"),
    )
    expanded = _fb_xml(
        _fb_node("Menu", bounds="[20,20][200,80]"),
        _fb_node("Tìm bạn bè", bounds="[70,1180][500,1260]"),
    )
    suggestions = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,300][400,345]"),
        _fb_node("2 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    dev = _FlowDevice(home, menu, expanded, suggestions)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "open_surface": True,
            "target_count": 1,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 1
    assert result["surface"]["ready"] is True
    assert dev.clicks[:3] == [(90, 208), (255, 940), (285, 1220)]


def test_flow_fb_connect_visible_people_closes_detail_before_opening_surface(
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    detail = _fb_xml(
        _fb_node("Đóng", bounds="[35,147][161,273]", clickable=True),
        _fb_node("Bài viết của Some Page", bounds="[60,360][700,430]"),
    )
    home = _fb_xml(_fb_node("Menu", bounds="[40,180][140,260]"))
    menu = _fb_xml(
        _fb_node("Menu", bounds="[20,20][200,80]"),
        _fb_node("Tìm bạn bè", bounds="[70,1180][500,1260]"),
    )
    suggestions = _fb_xml(
        _fb_node("Bạn bè", bounds="[20,20][300,80]"),
        _fb_node("Gợi ý", bounds="[20,90][250,150]"),
        _fb_node("Nguyen Van A", bounds="[40,300][400,345]"),
        _fb_node("2 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    dev = _FlowDevice(detail, home, menu, suggestions)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "open_surface": True,
            "target_count": 1,
            "dry_run": True,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["reason"] == "dry_run"
    assert result["eligible_count"] == 1
    assert result["surface"]["attempts"][:3] == [
        "close_detail_overlay",
        "tap_menu",
        "tap_find_friends",
    ]
    assert dev.clicks[:3] == [(98, 210), (90, 208), (285, 1220)]


def test_flow_social_open_author_from_post_match_verifies_profile(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    feed = _fb_xml(
        _fb_node(
            "Ảnh đại diện của Nguyen Van A",
            bounds="[42,451][182,591]",
            clickable=True,
        ),
        _fb_node("Nguyen Van A", bounds="[210,452][576,518]", clickable=True),
        _fb_node("AI automation builder", bounds="[105,840][1155,1320]"),
        _fb_node(
            "Nút Thích",
            bounds="[0,1505][223,1659]",
            clickable=True,
        ),
        _fb_node(
            "Bình luận",
            bounds="[227,1505][457,1659]",
            clickable=True,
        ),
    )
    profile = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[80,320][620,390]"),
        _fb_node("AI automation builder", bounds="[80,430][820,490]"),
        _fb_node("Thêm bạn bè", bounds="[600,720][980,810]", clickable=True),
    )
    dev = _FlowDevice(feed, profile)

    result = u2_exec_mod._flow_social_open_author_from_post_match(
        dev,
        {
            "platform": "facebook",
            "action": {
                "verified": True,
                "target_id": "ui_post:abc",
                "author_label": "Nguyen Van A",
                "author_tap": [393, 485],
                "like_bounds": [0, 1505, 223, 1659],
                "comment_bounds": [227, 1505, 457, 1659],
                "matched_keywords": ["AI"],
            },
            "required_keywords": ["AI"],
            "min_score": 80,
        },
    )

    assert result["verified"] is True
    assert result["source"] == "matched_feed_post_author"
    assert result["name"] == "Nguyen Van A"
    assert result["source_post_target_id"] == "ui_post:abc"
    assert result["action_bounds"] == [600, 720, 980, 810]
    assert dev.clicks == [(393, 485)]


def test_flow_social_open_author_closes_comment_overlay_before_author_tap(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    overlay = _fb_xml(
        _fb_node("Viết bình luận", bounds="[80,2080][920,2180]"),
        _fb_node("Đóng", bounds="[980,120][1060,200]", clickable=True),
    )
    feed = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[210,452][576,518]", clickable=True),
        _fb_node("AI automation builder", bounds="[105,840][1155,1320]"),
        _fb_node("Nút Thích", bounds="[0,1505][223,1659]", clickable=True),
        _fb_node("Bình luận", bounds="[227,1505][457,1659]", clickable=True),
    )
    profile = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[80,320][620,390]"),
        _fb_node("AI automation builder", bounds="[80,430][820,490]"),
        _fb_node("Thêm bạn bè", bounds="[600,720][980,810]", clickable=True),
    )
    dev = _FlowDevice(overlay, feed, profile)

    result = u2_exec_mod._flow_social_open_author_from_post_match(
        dev,
        {
            "platform": "facebook",
            "action": {
                "verified": True,
                "target_id": "ui_post:abc",
                "author_label": "Nguyen Van A",
                "author_tap": [393, 485],
                "like_bounds": [0, 1505, 223, 1659],
                "comment_bounds": [227, 1505, 457, 1659],
                "matched_keywords": ["AI"],
            },
            "required_keywords": ["AI"],
            "min_score": 80,
        },
    )

    assert result["verified"] is True
    assert dev.clicks == [(1020, 160), (393, 485)]


def test_fb_visible_post_candidates_include_author_binding():
    feed = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[210,452][576,518]", clickable=True),
        _fb_node("AI automation builder", bounds="[105,840][1155,1320]"),
        _fb_node(
            "Nút Thích",
            bounds="[0,1505][223,1659]",
            clickable=True,
        ),
        _fb_node(
            "Bình luận",
            bounds="[227,1505][457,1659]",
            clickable=True,
        ),
    )

    _candidates, qualified, _expand = u2_exec_mod._fb_visible_post_candidates(
        feed,
        keywords=u2_exec_mod._fb_scan_keyword_terms(["AI"]),
        match_mode="any",
        seen_fingerprints=set(),
        seen_expand_keys=set(),
        like_terms=["nut thich", "thich", "like"],
        liked_terms=["da thich", "liked"],
        comment_terms=["binh luan", "comment"],
        forbidden_context_terms=[],
    )

    assert len(qualified) == 1
    assert qualified[0]["author_label"] == "Nguyen Van A"
    assert qualified[0]["author_tap"] == [393, 485]


def test_flow_social_scan_posts_interact_forwards_author_binding(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    feed = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[210,452][576,518]", clickable=True),
        _fb_node("AI automation builder", bounds="[105,840][1155,1320]"),
        _fb_node("Nút Thích", bounds="[0,1505][223,1659]", clickable=True),
        _fb_node("Bình luận", bounds="[227,1505][457,1659]", clickable=True),
    )
    dev = _FlowDevice(feed)

    result = u2_exec_mod._flow_social_scan_posts_interact(
        dev,
        {
            "keywords": ["AI"],
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["verified"] is True
    assert result["actions"][0]["author_label"] == "Nguyen Van A"
    assert result["actions"][0]["author_tap"] == [393, 485]


def test_flow_social_scan_posts_interact_can_skip_like_and_comment(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    feed = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[210,452][576,518]", clickable=True),
        _fb_node("AI automation builder", bounds="[105,840][1155,1320]"),
        _fb_node("Nút Thích", bounds="[0,1505][223,1659]", clickable=True),
        _fb_node("Bình luận", bounds="[227,1505][457,1659]", clickable=True),
    )
    dev = _FlowDevice(feed)

    result = u2_exec_mod._flow_social_scan_posts_interact(
        dev,
        {
            "keywords": ["AI"],
            "target_count": 1,
            "max_scrolls": 0,
            "like_post": False,
            "require_comment": False,
        },
    )

    assert result["verified"] is True
    assert result["liked_count"] == 0
    assert result["commented_count"] == 0
    assert result["actions"][0]["liked"] is False
    assert dev.clicks == []


def test_flow_social_open_commenter_from_post_match_verifies_profile(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    comments = _fb_xml(
        _fb_node("Phù hợp nhất", bounds="[40,450][400,500]"),
        _fb_node("Tran Van B", bounds="[180,740][420,790]", clickable=True),
        _fb_node("Mình đang làm AI automation", bounds="[180,800][1000,860]"),
        _fb_node("Viết bình luận…", bounds="[40,2280][1040,2340]"),
    )
    profile = _fb_xml(
        _fb_node("Tran Van B", bounds="[80,320][620,390]"),
        _fb_node("AI automation consultant", bounds="[80,430][820,490]"),
        _fb_node("Thêm bạn bè", bounds="[600,720][980,810]", clickable=True),
    )
    dev = _FlowDevice(comments, profile)

    result = u2_exec_mod._flow_social_open_commenter_from_post_match(
        dev,
        {
            "platform": "facebook",
            "action": {
                "verified": True,
                "target_id": "ui_post:abc",
                "comment_bounds": [227, 1505, 457, 1659],
            },
            "required_keywords": ["AI"],
            "min_score": 80,
        },
    )

    assert result["verified"] is True
    assert result["source"] == "matched_feed_post_commenter"
    assert result["name"] == "Tran Van B"
    assert result["comment_sheet_opened"] is True
    assert result["action_bounds"] == [600, 720, 980, 810]
    assert dev.clicks == [(342, 1582), (260, 765)]


def test_flow_social_open_author_from_post_match_skips_unsupported_platform():
    result = u2_exec_mod._flow_social_open_author_from_post_match(
        _FlowDevice(_fb_xml()),
        {"platform": "instagram", "action": {}},
    )

    assert result["verified"] is False
    assert result["reason"] == "unsupported_platform"


def test_flow_fb_open_author_from_post_match_fails_closed_without_binding():
    result = u2_exec_mod._flow_fb_open_author_from_post_match(
        _FlowDevice(_fb_xml()),
        {"action": {"verified": True, "target_id": "ui_post:abc"}},
    )

    assert result["verified"] is False
    assert result["reason"] == "author_binding_missing"


# ── Batch tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_batch_empty(executor):
    exc, dev, pool = executor
    result = await exc.run_batch("serial", [], early_exit=True)
    assert result["ok"] is True
    assert result["results"] == []
    pool.run_locked.assert_not_called()


@pytest.mark.asyncio
async def test_run_batch_click_success(executor):
    exc, dev, pool = executor
    assert exc.ui_generation("serial") == 0
    result = await exc.run_batch("serial", [
        {"op": "click", "x": 100, "y": 200},
    ])
    assert result["ok"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["op"] == "click"
    assert result["results"][0]["ok"] is True
    assert result["total_ms"] >= 0
    assert result["results"][0]["duration_ms"] >= 0
    dev.click.assert_called_once_with(100, 200)
    assert exc.ui_generation("serial") == 2
    assert exc.ui_mutation_in_flight("serial") == 0


@pytest.mark.asyncio
async def test_run_batch_press_key_falls_back_to_adb_home_intent(executor, monkeypatch):
    exc, dev, pool = executor
    dev.press.side_effect = RuntimeError("JSON-RPC HTTP 502")
    adb_calls: list[tuple[str, str, int]] = []

    def fake_adb_shell(serial: str, cmd: str, timeout: int = 5):
        adb_calls.append((serial, cmd, timeout))
        return "", 0

    monkeypatch.setattr(u2_exec_mod, "_adb_shell", fake_adb_shell)

    result = await exc.run_batch("serial-1", [
        {"op": "press_key", "key": "home"},
    ])

    assert result["ok"] is True
    assert result["results"][0]["ok"] is True
    dev.press.assert_called_once_with("home")
    assert adb_calls == [
        ("serial-1", "am start -a android.intent.action.MAIN -c android.intent.category.HOME", 5)
    ]
    assert exc.ui_mutation_in_flight("serial-1") == 0


@pytest.mark.asyncio
async def test_run_batch_http_direct_touch_avoids_u2_session_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        calls.append(payload)
        return True, ""

    exc = U2Executor(pool=pool, loop=event_loop, http_rpc=http_rpc)

    result = await exc.run_batch(
        "serial",
        [
            {"op": "click", "x": 100, "y": 200},
            {"op": "sleep", "seconds": 0},
            {"op": "swipe", "fx": 10, "fy": 20, "tx": 30, "ty": 40, "duration": 0.12},
        ],
    )

    assert result["ok"] is True
    assert [call["method"] for call in calls] == ["click", "swipe"]
    assert calls[0]["params"] == [100, 200]
    assert calls[1]["params"] == [10, 20, 30, 40, 4]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_direct_batches"] == 1
    assert stats["http_direct_actions"] == 3
    assert exc.ui_generation("serial") == 2


@pytest.mark.asyncio
async def test_run_batch_http_direct_touch_early_exits_on_rpc_error(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_rpc(_serial: str, _payload: dict, _timeout: float) -> tuple[bool, str]:
        nonlocal calls
        calls += 1
        return False, "boom"

    exc = U2Executor(pool=pool, loop=event_loop, http_rpc=http_rpc)

    result = await exc.run_batch(
        "serial",
        [
            {"op": "click", "x": 100, "y": 200},
            {"op": "click", "x": 300, "y": 400},
        ],
    )

    assert result["ok"] is False
    assert result["stopped_at"] == 0
    assert result["results"][0]["error"] == "boom"
    assert calls == 1
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_direct_batches"] == 1
    assert stats["http_direct_failures"] == 1


@pytest.mark.asyncio
async def test_run_batch_click_spec_xpath_bounds_uses_http_direct(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    calls: list[dict] = []

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        calls.append(payload)
        return True, ""

    exc = U2Executor(pool=pool, loop=event_loop, http_rpc=http_rpc)

    result = await exc.run_batch(
        "serial",
        [
            {
                "op": "click_spec",
                "spec": {"xpath": '//*[@bounds="[100,200][300,250]"]'},
            },
        ],
    )

    assert result["ok"] is True
    assert calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [200, 225]}
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["click_spec_http_direct"] == 1
    assert stats["click_spec_http_direct_bounds"] == 1
    assert stats["http_direct_batches"] == 1


@pytest.mark.asyncio
async def test_run_batch_read_only_actions_do_not_advance_ui_generation(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.exists = True
    dev.return_value = ui_obj

    await exc.run_batch("serial", [
        {"op": "exists", "selector": {"text": "OK"}},
        {"op": "sleep", "seconds": 0},
    ])

    assert exc.ui_generation("serial") == 0


@pytest.mark.asyncio
async def test_run_batch_mutation_is_marked_in_flight_until_completion(executor):
    exc, dev, pool = executor
    started = asyncio.Event()
    release = asyncio.Event()

    async def _run_locked(serial: str, fn):
        started.set()
        await release.wait()
        return fn(dev)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    task = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "click", "x": 100, "y": 200}],
        )
    )
    await asyncio.wait_for(started.wait(), timeout=0.5)

    assert exc.ui_generation("serial") == 1
    assert exc.ui_mutation_in_flight("serial") == 1

    release.set()
    result = await asyncio.wait_for(task, timeout=0.5)

    assert result["ok"] is True
    assert exc.ui_generation("serial") == 2
    assert exc.ui_mutation_in_flight("serial") == 0


@pytest.mark.asyncio
async def test_run_batch_exists_returns_value(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.exists = True
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "exists", "selector": {"text": "OK"}},
    ])
    assert result["ok"] is True
    assert result["results"][0]["value"] is True


@pytest.mark.asyncio
async def test_run_batch_early_exit(executor):
    exc, dev, pool = executor

    # click succeeds, get_text fails (selector not found)
    ui_obj = MagicMock()
    ui_obj.exists = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click", "x": 10, "y": 20},
        {"op": "get_text", "selector": {"text": "missing"}},
        {"op": "click", "x": 30, "y": 40},
    ], early_exit=True)

    assert result["ok"] is False
    assert result["stopped_at"] == 1
    assert len(result["results"]) == 2
    # Third action should NOT have been called
    assert dev.click.call_count == 1


@pytest.mark.asyncio
async def test_run_batch_no_early_exit(executor):
    """With early_exit=False, all actions run even if some fail."""
    exc, dev, pool = executor

    ui_obj = MagicMock()
    ui_obj.exists = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click", "x": 10, "y": 20},
        {"op": "get_text", "selector": {"text": "missing"}},
        {"op": "click", "x": 30, "y": 40},
    ], early_exit=False)

    assert len(result["results"]) == 3
    assert result["results"][0]["ok"] is True
    assert result["results"][1]["ok"] is False
    assert result["results"][2]["ok"] is True


@pytest.mark.asyncio
async def test_unknown_op_fails_cleanly(executor):
    exc, dev, pool = executor
    result = await exc.run_batch("serial", [
        {"op": "nonexistent"},
    ])
    assert result["ok"] is False
    assert result["stopped_at"] == 0
    assert "unknown op" in result["results"][0]["error"]
    assert result["total_ms"] >= 0
    assert result["results"][0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_session_unavailable(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock(side_effect=RuntimeError("no device"))
    pool.evict = AsyncMock()
    exc = U2Executor(pool=pool, loop=event_loop)

    result = await exc.run_batch("serial", [{"op": "click", "x": 1, "y": 2}])
    assert result["ok"] is False
    assert result["stopped_at"] == 0
    # Phase 2 moved get_session into the per-action loop so errors are attributed
    # to the specific action that tried to acquire the session.
    assert "no device" in result["error"]


@pytest.mark.asyncio
async def test_dump_hierarchy_forwards_optional_dump_kwargs(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.evict = AsyncMock()
    mock_device.dump_hierarchy.return_value = "<hierarchy />"
    exc = U2Executor(pool=pool, loop=event_loop)

    result = await exc.run_batch(
        "serial",
        [{"op": "dump_hierarchy", "compressed": True, "pretty": True, "max_depth": 20}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] == "<hierarchy />"
    mock_device.dump_hierarchy.assert_called_once_with(compressed=True, pretty=True, max_depth=20)


@pytest.mark.asyncio
async def test_dump_hierarchy_prefers_http_dump(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    xml = '<?xml version="1.0"?><hierarchy><node /></hierarchy>'
    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )
    result = await exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
    assert result["ok"] is True
    assert result["results"][0]["value"] == xml
    mock_device.dump_hierarchy.assert_not_called()


@pytest.mark.asyncio
async def test_direct_http_dump_marks_pool_health(event_loop, mock_device):
    xml = "<hierarchy />"
    pool = U2SessionPool(loop=event_loop, connect_fn=MagicMock(return_value=mock_device))
    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])

    assert result["ok"] is True
    stats = pool.stats_snapshot(reset=False)
    assert stats["direct_http_health_marks"] == 1
    assert stats["direct_http_healthy_serials"] == 1


@pytest.mark.asyncio
async def test_dump_hierarchy_singleflight_deduplicates_concurrent_http_dump(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = '<?xml version="1.0"?><hierarchy><node /></hierarchy>'
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    first = asyncio.create_task(
        exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
    )
    while not started.is_set():
        await asyncio.sleep(0)
    joined = [
        asyncio.create_task(
            exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
        )
        for _index in range(5)
    ]
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(first, *joined)

    assert calls == 1
    assert all(result["ok"] is True for result in results)
    assert all(result["results"][0]["value"] == xml for result in results)
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_singleflight_leaders"] == 1
    assert stats["dump_singleflight_joins"] == 5
    assert stats["dump_background_singleflight_leaders"] == 1
    assert stats["dump_background_singleflight_joins"] == 5
    assert stats["hierarchy_background_requests"] == 6
    assert stats["hierarchy_background_success"] == 6
    pool.run_locked.assert_not_called()


@pytest.mark.asyncio
async def test_dump_hierarchy_singleflight_is_scoped_by_visible_lane(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_no = calls
        if call_no == 1:
            started.set()
            release.wait(timeout=5.0)
        return (
            f'<?xml version="1.0"?><hierarchy><node text="{call_no}" /></hierarchy>'
        )

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    background = asyncio.create_task(
        exc.run_batch("serial", [{"op": "dump_hierarchy", "timeout": 5.0}])
    )
    while not started.is_set():
        await asyncio.sleep(0)

    visible = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "dump_hierarchy", "timeout": 5.0}],
            priority="visible",
        )
    )
    for _index in range(100):
        with calls_lock:
            if calls >= 2:
                break
        await asyncio.sleep(0.01)

    visible_result = await asyncio.wait_for(visible, timeout=1.0)
    assert background.done() is False
    release.set()
    background_result = await background

    assert calls == 2
    assert background_result["ok"] is True
    assert visible_result["ok"] is True
    assert 'text="1"' in background_result["results"][0]["value"]
    assert 'text="2"' in visible_result["results"][0]["value"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_background_singleflight_leaders"] == 1
    assert stats["dump_visible_singleflight_leaders"] == 1
    assert stats["dump_singleflight_joins"] == 0
    assert stats["hierarchy_background_requests"] == 1
    assert stats["hierarchy_visible_requests"] == 1
    assert stats["hierarchy_background_success"] == 1
    assert stats["hierarchy_visible_success"] == 1


@pytest.mark.asyncio
async def test_background_dump_deadline_grace_allows_near_complete_singleflight(
    event_loop,
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod, "U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS", 200)
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = '<?xml version="1.0"?><hierarchy><node /></hierarchy>'
    started = threading.Event()
    release = threading.Event()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    task = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "dump_hierarchy", "timeout": 5.0}],
            priority="background",
            deadline_ms=20,
        )
    )
    while not started.is_set():
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    release.set()

    result = await asyncio.wait_for(task, timeout=1.0)

    assert result["ok"] is True
    assert result["results"][0]["value"] == xml
    stats = exc.stats_snapshot(reset=False)
    assert stats["background_dump_deadline_grace_applied"] == 2
    assert stats["background_deadline_drops"] == 0


@pytest.mark.asyncio
async def test_visible_dump_deadline_is_not_extended_by_background_grace(
    event_loop,
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod, "U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS", 200)
    pool = AsyncMock()
    pool.evict = AsyncMock()
    started = threading.Event()
    release = threading.Event()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        started.set()
        release.wait(timeout=1.0)
        return '<?xml version="1.0"?><hierarchy><node /></hierarchy>'

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    task = asyncio.create_task(
        exc.run_batch(
            "serial",
            [{"op": "dump_hierarchy", "timeout": 5.0}],
            priority="visible",
            deadline_ms=20,
        )
    )
    while not started.is_set():
        await asyncio.sleep(0)

    result = await asyncio.wait_for(task, timeout=1.0)
    release.set()

    assert result["ok"] is False
    assert "deadline exceeded while waiting for dump_hierarchy" in result["error"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["background_dump_deadline_grace_applied"] == 0
    assert stats["visible_deadline_drops"] == 1


def test_background_dump_deadline_grace_scales_with_waiting_backlog(
    event_loop,
    monkeypatch,
):
    monkeypatch.setattr(u2_exec_mod, "U2_BACKGROUND_DUMP_DEADLINE_GRACE_MS", 100)
    monkeypatch.setattr(
        u2_exec_mod,
        "U2_BACKGROUND_DUMP_DEADLINE_GRACE_PER_WAVE_MS",
        10,
    )
    monkeypatch.setattr(u2_exec_mod, "U2_EXECUTOR_BACKGROUND_CONCURRENCY", 4)
    monkeypatch.setattr(u2_exec_mod, "U2_EXECUTOR_CONCURRENCY", 8)
    pool = AsyncMock()
    pool.evict = AsyncMock()
    exc = U2Executor(pool=pool, loop=event_loop)
    exc._background_waiting = 9

    deadline = exc._single_dump_deadline_ms(1000, priority="background")

    assert deadline == 1130
    stats = exc.stats_snapshot(reset=False)
    assert stats["background_dump_deadline_grace_applied"] == 1


@pytest.mark.asyncio
async def test_concurrent_wait_exists_same_selector_coalesces_xml_poll(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" />
    </hierarchy>
    """
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    action = {
        "op": "wait_exists",
        "selector": {"resourceId": "com.app:id/ready"},
        "timeout": 5.0,
    }
    first = asyncio.create_task(exc.run_batch("serial", [action], priority="visible"))
    while not started.is_set():
        await asyncio.sleep(0)
    joined = [
        asyncio.create_task(exc.run_batch("serial", [action], priority="visible"))
        for _index in range(5)
    ]
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(first, *joined)

    assert calls == 1
    assert all(result["ok"] is True for result in results)
    assert all(result["results"][0]["value"] is True for result in results)
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_poll_coalesced_leaders"] == 1
    assert stats["xml_poll_coalesced_joins"] == 5
    assert stats["http_wait_batches"] == 6
    assert stats["http_wait_polls"] == 1


@pytest.mark.asyncio
async def test_visible_wait_does_not_coalesce_with_background_wait(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" />
    </hierarchy>
    """
    started = threading.Event()
    release = threading.Event()

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        started.set()
        release.wait(timeout=1.0)
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    action = {
        "op": "wait_exists",
        "selector": {"resourceId": "com.app:id/ready"},
        "timeout": 5.0,
    }
    visible = asyncio.create_task(exc.run_batch("serial", [action], priority="visible"))
    while not started.is_set():
        await asyncio.sleep(0)
    background = asyncio.create_task(exc.run_batch("serial", [action], priority="background"))
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(visible, background)

    assert all(result["ok"] is True for result in results)
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_poll_coalesced_leaders"] == 2
    assert stats["xml_poll_coalesced_joins"] == 0


@pytest.mark.asyncio
async def test_dump_hierarchy_cache_reuses_short_ttl(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return f"<?xml version='1.0'?><hierarchy><node text='{calls}' /></hierarchy>"

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    first = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    second = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])

    assert calls == 1
    assert first["results"][0]["value"] == second["results"][0]["value"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_cache_hits"] == 1
    assert stats["dump_cache_stores"] >= 1


@pytest.mark.asyncio
async def test_dump_hierarchy_force_fresh_bypasses_short_ttl_cache(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return f"<?xml version='1.0'?><hierarchy><node text='{calls}' /></hierarchy>"

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    first = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    second = await exc.run_batch("serial", [{"op": "dump_hierarchy", "force_fresh_xml": True}])

    assert calls == 2
    assert first["results"][0]["value"] != second["results"][0]["value"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_cache_hits"] == 0
    assert stats["dump_cache_stores"] >= 2


@pytest.mark.asyncio
async def test_dump_then_exists_get_text_reuses_xml_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node index="0" text="Login" resource-id="com.app:id/login" class="android.widget.TextView" />
      <node index="1" text="Cancel" content-desc="Cancel button" enabled="true" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"text": "Login"}},
            {"op": "get_text", "selector": {"resourceId": "com.app:id/login"}},
            {"op": "exists", "selector": {"descriptionContains": "Cancel"}},
        ],
    )

    assert result["ok"] is True
    assert calls == 1
    assert result["results"][1]["value"] is True
    assert result["results"][2]["value"] == "Login"
    assert result["results"][3]["value"] is True
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_batch_optimized"] == 1
    assert stats["xml_parse_lxml"] == 1
    assert stats["xml_index_builds"] == 1
    assert stats["xml_u2_calls_avoided"] == 3
    assert stats["xml_selector_hits"] == 3


@pytest.mark.asyncio
async def test_xml_selector_lookup_cache_reuses_same_selector_on_same_index(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Login" resource-id="com.app:id/login" class="android.widget.TextView" />
    </hierarchy>
    """

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"resourceId": "com.app:id/login"}},
            {"op": "get_text", "selector": {"resourceId": "com.app:id/login"}},
            {"op": "exists", "selector": {"resourceId": "com.app:id/login"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is True
    assert result["results"][2]["value"] == "Login"
    assert result["results"][3]["value"] is True
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_selector_cache_stores"] == 1
    assert stats["xml_selector_cache_hits"] == 2


@pytest.mark.asyncio
async def test_xml_index_cache_reuses_parsed_dump_across_batches(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Login" resource-id="com.app:id/login" bounds="[100,200][200,250]" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    actions = [
        {"op": "dump_hierarchy"},
        {"op": "exists", "selector": {"resourceId": "com.app:id/login"}},
    ]

    first = await exc.run_batch("serial", actions)
    second = await exc.run_batch("serial", actions)

    assert first["ok"] is True
    assert second["ok"] is True
    assert dump_calls == 1
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["dump_cache_hits"] == 1
    assert stats["xml_parse_lxml"] == 1
    assert stats["xml_index_builds"] == 1
    assert stats["xml_index_cache_hits"] == 1
    assert stats["xml_index_cache_stores"] == 1


@pytest.mark.asyncio
async def test_xml_index_cache_survives_bypass_when_dump_content_same(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)
    act = {"op": "dump_hierarchy", "timeout": 0.1}
    key = exc._single_dump_cache_key("serial", act)

    first = await exc._run_single_dump_batch(
        serial="serial",
        act=act,
        early_exit=True,
        priority="visible",
        deadline_ms=None,
        batch_started=0.0,
        bypass_cache=True,
    )
    first_index = exc._xml_index_from_dump(
        key,
        str(first["results"][0]["value"] or ""),
        priority="visible",
    )
    second = await exc._run_single_dump_batch(
        serial="serial",
        act=act,
        early_exit=True,
        priority="visible",
        deadline_ms=None,
        batch_started=0.0,
        bypass_cache=True,
    )
    second_index = exc._xml_index_from_dump(
        key,
        str(second["results"][0]["value"] or ""),
        priority="visible",
    )

    assert first_index is second_index
    assert dump_calls == 2
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_parse_lxml"] == 1
    assert stats["xml_index_builds"] == 1
    assert stats["xml_index_cache_hits"] == 1


@pytest.mark.asyncio
async def test_dump_then_click_selector_uses_xml_bounds_http_direct(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    rpc_calls: list[dict] = []
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node index="0" text="Login" resource-id="com.app:id/login"
            class="android.widget.Button" clickable="true" bounds="[100,200][200,250]" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        rpc_calls.append(payload)
        return True, ""

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=http_dump,
        http_rpc=http_rpc,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"text": "Login"}},
            {"op": "click_selector", "selector": {"resourceId": "com.app:id/login"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is True
    assert result["results"][2]["value"] is True
    assert dump_calls == 1
    assert rpc_calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [150, 225]}
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_batch_optimized"] == 1
    assert stats["xml_click_fused"] == 1
    assert stats["http_direct_actions"] == 1
    assert stats["xml_u2_calls_avoided"] == 2
    assert exc.ui_generation("serial") == 2


@pytest.mark.asyncio
async def test_dump_then_click_selector_missing_returns_false_without_rpc(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: "<?xml version='1.0'?><hierarchy />",
        http_rpc=lambda _s, payload, _t: (rpc_calls.append(payload) is None, ""),
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "click_selector", "selector": {"text": "Missing"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is False
    assert rpc_calls == []
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_click_misses"] == 1


@pytest.mark.asyncio
async def test_dump_then_click_spec_uses_xml_index_and_http_direct(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    rpc_calls: list[dict] = []
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Confirm" class="android.widget.Button" clickable="true"
            bounds="[40,1000][240,1080]" />
    </hierarchy>
    """

    def http_rpc(_serial: str, payload: dict, _timeout: float) -> tuple[bool, str]:
        rpc_calls.append(payload)
        return True, ""

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
        http_rpc=http_rpc,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "click_spec", "spec": {"by": "text", "value": "Confirm"}},
        ],
    )

    assert result["ok"] is True
    assert result["results"][1]["value"] is True
    assert rpc_calls == [
        {"jsonrpc": "2.0", "method": "click", "id": 1, "params": [140, 1040]}
    ]
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_click_fused"] == 1
    assert stats["click_spec_http_direct"] == 1
    assert stats["click_spec_http_direct_bounds"] == 0
    assert stats["xml_selector_hits"] == 1


@pytest.mark.asyncio
async def test_wait_exists_uses_http_dump_poll_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    dump_calls = 0
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Ready" resource-id="com.app:id/ready" bounds="[10,20][110,60]" />
    </hierarchy>
    """

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xml

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [{"op": "wait_exists", "selector": {"resourceId": "com.app:id/ready"}, "timeout": 0.1}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    assert result["results"][0]["polls"] == 1
    assert dump_calls == 1
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_batches"] == 1
    assert stats["http_wait_hits"] == 1
    assert stats["http_wait_polls"] == 1


@pytest.mark.asyncio
async def test_wait_exists_spec_uses_http_dump_poll_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xml = """<?xml version='1.0'?>
    <hierarchy>
      <node text="Confirm" class="android.widget.Button" bounds="[40,1000][240,1080]" />
    </hierarchy>
    """

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch(
        "serial",
        [{"op": "wait_exists_spec", "spec": {"by": "text", "value": "Confirm"}, "timeout": 0.1}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_batches"] == 1
    assert stats["http_wait_hits"] == 1


@pytest.mark.asyncio
async def test_wait_exists_http_poll_returns_false_on_timeout(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: "<?xml version='1.0'?><hierarchy />",
    )

    result = await exc.run_batch(
        "serial",
        [{"op": "wait_exists", "selector": {"text": "Missing"}, "timeout": 0.0}],
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is False
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_misses"] == 1


@pytest.mark.asyncio
async def test_wait_gone_uses_http_dump_poll_without_u2_lock(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xmls = [
        """<?xml version='1.0'?>
        <hierarchy>
          <node text="Loading" resource-id="com.app:id/loading" />
        </hierarchy>
        """,
        "<?xml version='1.0'?><hierarchy />",
    ]
    dump_calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xmls[min(dump_calls - 1, len(xmls) - 1)]

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [
            {
                "op": "wait_gone",
                "selector": {"resourceId": "com.app:id/loading"},
                "timeout": 0.15,
            }
        ],
        priority="visible",
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    assert result["results"][0]["polls"] == 2
    assert dump_calls == 2
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_batches"] == 1
    assert stats["http_wait_hits"] == 1
    assert stats["http_wait_polls"] == 2


@pytest.mark.asyncio
async def test_wait_exists_poll_bypasses_cache_after_first_poll(event_loop):
    pool = AsyncMock()
    pool.run_locked = AsyncMock()
    pool.evict = AsyncMock()
    xmls = [
        "<?xml version='1.0'?><hierarchy />",
        """<?xml version='1.0'?>
        <hierarchy>
          <node text="Ready" resource-id="com.app:id/ready" />
        </hierarchy>
        """,
    ]
    dump_calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal dump_calls
        dump_calls += 1
        return xmls[min(dump_calls - 1, len(xmls) - 1)]

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    result = await exc.run_batch(
        "serial",
        [
            {
                "op": "wait_exists",
                "selector": {"resourceId": "com.app:id/ready"},
                "timeout": 0.15,
            }
        ],
        priority="visible",
    )

    assert result["ok"] is True
    assert result["results"][0]["value"] is True
    assert result["results"][0]["polls"] == 2
    assert dump_calls == 2
    pool.run_locked.assert_not_called()
    stats = exc.stats_snapshot(reset=False)
    assert stats["http_wait_hits"] == 1
    assert stats["dump_cache_hits"] == 0


@pytest.mark.asyncio
async def test_xml_batch_optimizer_falls_back_for_xpath_selector(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.evict = AsyncMock()
    mock_device.dump_hierarchy.return_value = "<hierarchy />"
    xpath_obj = MagicMock()
    xpath_obj.exists = True
    mock_device.xpath.return_value = xpath_obj

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: "<hierarchy />",
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "exists", "selector": {"xpath": "//node"}},
        ],
    )

    assert result["ok"] is True
    assert pool.run_locked.await_count == 1
    mock_device.xpath.assert_called_once_with("//node")
    stats = exc.stats_snapshot(reset=False)
    assert stats["xml_optimizer_fallbacks"] == 1
    assert stats["xml_batch_optimized"] == 0


@pytest.mark.asyncio
async def test_xml_batch_get_text_missing_respects_early_exit(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    xml = "<?xml version='1.0'?><hierarchy><node text='Login' /></hierarchy>"

    exc = U2Executor(
        pool=pool,
        loop=event_loop,
        http_dump=lambda _s, _t, _c: xml,
    )

    result = await exc.run_batch(
        "serial",
        [
            {"op": "dump_hierarchy"},
            {"op": "get_text", "selector": {"text": "Missing"}},
            {"op": "exists", "selector": {"text": "Login"}},
        ],
    )

    assert result["ok"] is False
    assert result["stopped_at"] == 1
    assert len(result["results"]) == 2
    assert result["results"][1]["error"] == "selector not found"
    pool.run_locked.assert_not_called()


@pytest.mark.asyncio
async def test_ui_mutation_invalidates_dump_hierarchy_cache(event_loop, mock_device):
    pool = AsyncMock()

    async def _run_locked(serial: str, fn):
        return fn(mock_device)

    pool.run_locked = AsyncMock(side_effect=_run_locked)
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        return f"<?xml version='1.0'?><hierarchy><node text='{calls}' /></hierarchy>"

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    first = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    await exc.run_batch("serial", [{"op": "click", "x": 1, "y": 2}])
    second = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])

    assert calls == 2
    assert first["results"][0]["value"] != second["results"][0]["value"]


@pytest.mark.asyncio
async def test_dump_hierarchy_breaker_drops_background_visible_bypasses(event_loop):
    pool = AsyncMock()
    pool.evict = AsyncMock()
    calls = 0

    def http_dump(_serial: str, _timeout: float, _compressed: bool) -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError("read timeout")

    exc = U2Executor(pool=pool, loop=event_loop, http_dump=http_dump)

    for _index in range(3):
        result = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
        assert result["ok"] is False

    dropped = await exc.run_batch("serial", [{"op": "dump_hierarchy"}])
    visible = await exc.run_batch(
        "serial",
        [{"op": "dump_hierarchy"}],
        priority="visible",
    )

    assert calls == 4
    assert dropped["ok"] is False
    assert "breaker open" in dropped["error"]
    assert visible["ok"] is False
    assert "read timeout" in visible["error"]
    stats = exc.stats_snapshot(reset=False)
    assert stats["breaker_drops"] == 1
    assert stats["breaker_opens"] >= 1


@pytest.mark.asyncio
async def test_screenshot_uses_the_device_jpeg_without_re_encoding(executor):
    """takeScreenshot already returns base64 JPEG — pass it straight through.

    Decoding it and re-encoding as PNG cost ~370ms and 2.2MB per capture on a
    real 1260x2800 screen without improving OCR at all (identical box count and
    mean confidence), because the pixels went through JPEG either way.
    """
    exc, dev, pool = executor
    dev.jsonrpc.takeScreenshot.return_value = "QUJD"  # base64 for "ABC"

    result = await exc.run_batch("serial", [
        {"op": "screenshot"},
    ])
    assert result["ok"] is True
    assert result["results"][0]["value"] == "QUJD"
    dev.screenshot.assert_not_called()


@pytest.mark.asyncio
async def test_screenshot_falls_back_to_pillow_when_rpc_unusable(executor):
    """A stub or changed API must not be shipped to the farm as an image."""
    from PIL import Image

    exc, dev, pool = executor
    dev.jsonrpc.takeScreenshot.return_value = None
    dev.screenshot.return_value = Image.new("RGB", (4, 3), (1, 2, 3))

    result = await exc.run_batch("serial", [
        {"op": "screenshot"},
    ])
    assert result["ok"] is True
    decoded = Image.open(io.BytesIO(base64.b64decode(result["results"][0]["value"])))
    assert decoded.format == "JPEG"
    assert decoded.size == (4, 3)


@pytest.mark.asyncio
async def test_screenshot_fails_loudly_when_device_returns_nothing(executor):
    exc, dev, pool = executor
    dev.jsonrpc.takeScreenshot.return_value = None
    dev.screenshot.return_value = None

    result = await exc.run_batch("serial", [
        {"op": "screenshot"},
    ])
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_open_url_uses_uiautomator_device_open_url(executor):
    exc, dev, pool = executor

    result = await exc.run_batch("serial", [
        {"op": "open_url", "url": "https://example.com/path?q=1"},
    ])

    assert result["ok"] is True
    assert result["results"][0]["op"] == "open_url"
    dev.open_url.assert_called_once_with("https://example.com/path?q=1")


def test_selector_normalizes_description_startswith_alias(mock_device):
    _resolve(mock_device, {"descriptionStartswith": "Nút Thích"})

    mock_device.assert_called_once_with(descriptionStartsWith="Nút Thích")


@pytest.mark.asyncio
async def test_click_selector_default_timeout_is_fast(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.click_exists.return_value = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click_selector", "selector": {"text": "missing"}},
    ])

    assert result["ok"] is True
    ui_obj.click_exists.assert_called_once_with(timeout=0.35)


@pytest.mark.asyncio
async def test_click_spec_default_timeout_is_fast(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.click_exists.return_value = False
    dev.return_value = ui_obj

    result = await exc.run_batch("serial", [
        {"op": "click_spec", "spec": {"by": "text", "value": "missing"}},
    ])

    assert result["ok"] is True
    ui_obj.click_exists.assert_called_once_with(timeout=0.35)


@pytest.mark.asyncio
async def test_swipe_default_duration_is_fast(executor):
    exc, dev, pool = executor

    result = await exc.run_batch("serial", [
        {"op": "swipe", "fx": 100, "fy": 1000, "tx": 100, "ty": 300},
    ])

    assert result["ok"] is True
    dev.swipe.assert_called_once_with(100, 1000, 100, 300, duration=0.12)


@pytest.mark.asyncio
async def test_run_batch_sleep_op_is_bounded(executor, monkeypatch):
    exc, dev, pool = executor
    calls: list[float] = []
    monkeypatch.setattr("relay.u2_executor.time.sleep", calls.append)

    result = await exc.run_batch("serial", [{"op": "sleep", "seconds": 9.0}])

    assert result["ok"] is True
    assert calls == [3.0]


@pytest.mark.asyncio
async def test_wait_and_click_default_timeout_is_bounded(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.wait.return_value = False
    dev.return_value = ui_obj

    result = await exc.execute_flow("serial", "wait_and_click", {"selector": {"text": "missing"}})

    assert result["ok"] is True
    ui_obj.wait.assert_called_once_with(timeout=3.0)


@pytest.mark.asyncio
async def test_find_click_wait_default_timeouts_are_bounded(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.wait.return_value = True
    ui_obj.wait_gone.return_value = False
    dev.return_value = ui_obj

    result = await exc.execute_flow("serial", "find_click_wait", {"selector": {"text": "OK"}})

    assert result["ok"] is True
    ui_obj.wait.assert_called_once_with(timeout=3.0)
    ui_obj.wait_gone.assert_called_once_with(timeout=1.0)


@pytest.mark.asyncio
async def test_swipe_until_found_default_budget_is_bounded(executor):
    exc, dev, pool = executor
    ui_obj = MagicMock()
    ui_obj.exists = False
    dev.return_value = ui_obj
    dev.window_size.return_value = (1080, 2340)

    result = await exc.execute_flow("serial", "swipe_until_found", {"selector": {"text": "missing"}})

    assert result["ok"] is True
    assert result["value"]["swipes"] == 5
    assert dev.swipe.call_count == 5
    assert dev.swipe.call_args.kwargs == {"duration": 0.12}


# ── Selector resolution ──────────────────────────────────────────────────────


def test_selector_xpath_dispatch():
    dev = MagicMock()
    _resolve(dev, {"xpath": "//View"})
    dev.xpath.assert_called_once_with("//View")


def test_selector_kwargs_dispatch():
    dev = MagicMock()
    _resolve(dev, {"text": "OK"})
    dev.assert_called_once_with(text="OK")


def test_selector_empty_raises():
    dev = MagicMock()
    with pytest.raises(ValueError, match="selector required"):
        _resolve(dev, {})


def test_selector_unknown_keys_raises():
    dev = MagicMock()
    with pytest.raises(ValueError, match="unrecognised"):
        _resolve(dev, {"bogusKey": "val"})


def test_fb_row_labels_do_not_bleed_into_the_next_person():
    """Real Facebook cards sit ~40px apart; a pixel window swept in the neighbour.

    Captured from a physical device (Android 16, 1260x2800): three suggestion
    cards with no mutual-friend line, where the geometric window produced
    "Anh Bui Nguyễn Hoài Sơn" and would have recorded the request against the
    wrong identity.
    """
    def _card(name: str, top: int) -> str:
        return (
            f'<node class="android.widget.Button" content-desc="{name}" '
            f'clickable="true" package="com.facebook.katana" '
            f'bounds="[0,{top}][1260,{top + 438}]">'
            f'<node class="android.widget.ImageView" content-desc="{name}" '
            f'package="com.facebook.katana" bounds="[42,{top + 28}][364,{top + 350}]" />'
            f'<node class="android.view.ViewGroup" text="{name}" '
            f'package="com.facebook.katana" bounds="[406,{top + 42}][1218,{top + 103}]" />'
            f'<node class="android.widget.Button" content-desc="Thêm bạn bè" '
            f'clickable="true" package="com.facebook.katana" '
            f'bounds="[406,{top + 130}][1218,{top + 256}]" />'
            f'<node class="android.widget.Button" content-desc="Xóa {name}" '
            f'clickable="true" package="com.facebook.katana" '
            f'bounds="[406,{top + 284}][1218,{top + 410}]" />'
            f"</node>"
        )

    xml = _fb_xml(_card("Anh Bui", 1260), _card("Nguyễn Hoài Sơn", 1698))
    candidates, _qualified, _rejected = u2_exec_mod._fb_visible_connectable_people(
        xml,
        common_keywords=[],
        forbidden_keywords=[],
        min_score=0,
        require_common=False,
    )

    assert [item["display_name"] for item in candidates] == [
        "Anh Bui",
        "Nguyễn Hoài Sơn",
    ]
    # Each row sees only its own card, and never the dismiss button's copy.
    for item in candidates:
        assert "Xóa" not in item["row_text"]
    assert candidates[0]["target_id"] != candidates[1]["target_id"]


def test_flow_fb_connect_visible_people_re_aims_when_the_list_shifts(monkeypatch):
    """A card inserted above the suggestions moves every row down.

    Observed on a physical device: Facebook renders the friends surface, then
    adds an incoming friend-request card at the top. Coordinates captured before
    that insertion point at the wrong person, so the tap silently missed and the
    run reported request_not_verified.
    """
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    stale = _fb_xml(
        _fb_node("Thai Hanh", bounds="[40,300][400,345]"),
        _fb_node("2 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    # Same person, pushed down 500px by the card that appeared above.
    shifted = _fb_xml(
        _fb_node("Lời mời kết bạn", bounds="[20,60][600,120]"),
        _fb_node("Thai Hanh", bounds="[40,800][400,845]"),
        _fb_node("2 bạn chung", bounds="[40,846][400,890]"),
        _fb_node("Thêm bạn bè", bounds="[600,820][900,900]", clickable=True),
    )
    sent = _fb_xml(
        _fb_node("Lời mời kết bạn", bounds="[20,60][600,120]"),
        _fb_node("Thai Hanh", bounds="[40,800][400,845]"),
        _fb_node("Đã gửi lời mời", bounds="[600,820][900,900]", clickable=True),
    )
    # The surface opener is stubbed, so it consumes no dump: the first read the
    # flow performs is the re-aim, which must see the shifted layout.
    dev = _FlowDevice(shifted, sent)
    # Seeding surface XML is what makes the first scan second-hand, exactly as
    # open_surface does in production.
    monkeypatch.setattr(
        u2_exec_mod,
        "_fb_open_friend_suggestions_surface",
        lambda _dev, _p: {"ready": True, "xml": stale},
    )

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "open_surface": True,
            "target_count": 1,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["sent_count"] == 1
    # Tapped where the row actually is, not where it used to be.
    assert dev.clicks == [(750, 860)]


def test_flow_fb_connect_visible_people_verifies_by_identity_not_position(monkeypatch):
    """A banner appearing after the tap must not turn a real send into a failure.

    Observed on a physical device: after the request to "Huy trần" was sent,
    Facebook removed his row AND inserted a "X accepted your request" banner,
    which slid another person's Add Friend button into the tapped coordinates.
    The positional check then reported request_not_verified for a send that had
    actually gone through.
    """
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    before = _fb_xml(
        _fb_node("Huy trần", bounds="[40,300][400,345]"),
        _fb_node("2 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    # Huy trần is gone; a banner pushed "Cua Bun Rieu" into the tapped band.
    after = _fb_xml(
        _fb_node("Kieuu Duyenzz đã chấp nhận lời mời kết bạn của bạn.",
                 bounds="[20,60][1200,200]"),
        _fb_node("Cua Bun Rieu", bounds="[40,300][400,345]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    dev = _FlowDevice(before, after)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 1,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is True
    assert result["sent_count"] == 1
    assert result["sent"][0]["display_name"] == "Huy trần"
    assert result["skipped"] == []


def test_flow_fb_connect_visible_people_still_detects_a_tap_that_missed(monkeypatch):
    """The identity check must not rubber-stamp every tap as a send."""
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    unchanged = _fb_xml(
        _fb_node("Huy trần", bounds="[40,300][400,345]"),
        _fb_node("2 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    dev = _FlowDevice(unchanged)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {
            "target_count": 1,
            "max_scrolls": 0,
            "min_score": 40,
            "require_common": True,
        },
    )

    assert result["verified"] is False
    assert result["reason"] == "request_not_verified"
    assert result["sent_count"] == 0


def _feed_post_xml(like_label: str) -> str:
    """One keyword-matching feed post with the given like-button state."""
    return _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("Bai viet ve AI rat hay", bounds="[40,150][900,200]"),
        _fb_node(like_label, bounds="[100,300][250,360]", clickable=True),
        _fb_node("Binh luan", bounds="[300,300][450,360]", clickable=True),
    )


def test_post_identity_survives_being_liked():
    """The like button sits inside the post's own context band.

    Hashing that band wholesale gave a post one identity before the like and
    another after, so the seen-set stopped recognising it the moment it was
    liked — and the same post could be commented on again on the next sweep.
    """
    terms = u2_exec_mod._DEFAULT_SOCIAL_POST_TERMS
    seen = set()
    for label in ("Thich", "Bo thich"):
        candidates, _q, _e = u2_exec_mod._fb_visible_post_candidates(
            _feed_post_xml(label),
            keywords=["ai"],
            match_mode="any",
            seen_fingerprints=set(),
            seen_expand_keys=set(),
            like_terms=terms["like_terms"],
            liked_terms=terms["liked_terms"],
            comment_terms=terms["comment_terms"],
            forbidden_context_terms=terms["forbidden_context_terms"],
        )
        seen.add(candidates[0]["fingerprint"])

    assert len(seen) == 1


def test_like_is_confirmed_against_the_post_it_was_aimed_at(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    dev = _FlowDevice(_feed_post_xml("Thich"), _feed_post_xml("Bo thich"))

    result = u2_exec_mod._flow_social_scan_posts_interact(
        dev,
        {
            "platform": "facebook",
            "keywords": ["ai"],
            "match_mode": "any",
            "like_post": True,
            "comment_text": "",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["actions"][0]["liked"] is True
    assert result["actions"][0]["like_verified"] is True


def test_a_like_that_did_not_register_is_not_reported_as_liked(monkeypatch):
    """The tap used to be assumed successful — a miss looked exactly like a hit.

    This is the most frequently executed action in the system, so silently
    counting misses as likes makes every downstream number wrong.
    """
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    # Button unchanged after the tap: nothing happened.
    dev = _FlowDevice(_feed_post_xml("Thich"))

    result = u2_exec_mod._flow_social_scan_posts_interact(
        dev,
        {
            "platform": "facebook",
            "keywords": ["ai"],
            "match_mode": "any",
            "like_post": True,
            "comment_text": "",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    assert result["actions"][0]["liked"] is False
    assert result["actions"][0]["like_verified"] is False


def test_verification_can_be_declined_for_throughput(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    dev = _FlowDevice(_feed_post_xml("Thich"))

    result = u2_exec_mod._flow_social_scan_posts_interact(
        dev,
        {
            "platform": "facebook",
            "keywords": ["ai"],
            "match_mode": "any",
            "like_post": True,
            "verify_like": False,
            "comment_text": "",
            "target_count": 1,
            "max_scrolls": 0,
        },
    )

    action = result["actions"][0]
    # "liked" then means "tapped", and the payload says so rather than implying
    # a check that never ran.
    assert action["liked"] is True
    assert action["like_verified"] is False


def test_destructive_controls_are_never_tapped(monkeypatch):
    """Last line of defence, independent of whatever picked the coordinates.

    Every locating mistake ends the same way: a tap on the wrong control. On the
    friends surface the neighbour of "Thêm bạn bè" is "Gỡ", and one tap further
    is "Ẩn những người bạn có thể biết" — which removes the account's entire
    suggestion source permanently.
    """
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    # The Add Friend button's bounds overlap a "Gỡ" control: whatever the
    # scoring decided, the tap must not land.
    xml = _fb_xml(
        _fb_node("Nguyen Van A", bounds="[40,100][400,145]"),
        _fb_node("3 bạn chung", bounds="[40,146][400,190]"),
        _fb_node("Thêm bạn bè", bounds="[600,120][900,200]", clickable=True),
        _fb_node("Gỡ", bounds="[600,120][900,200]", clickable=True),
    )
    dev = _FlowDevice(xml)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"target_count": 1, "max_scrolls": 0, "min_score": 40, "require_common": True},
    )

    assert dev.clicks == []
    assert result["sent_count"] == 0
    assert result["skipped"][0]["reason"] == "blocked_destructive_control"


@pytest.mark.parametrize(
    "label",
    [
        "Gỡ",
        "Xóa",
        "Ẩn những người bạn có thể biết",
        "Báo cáo bài viết",
        "Chặn",
        "Bỏ theo dõi",
        "Hủy kết bạn",
        "Rời nhóm",
        "Chấp nhận",
        # Observed on a real device: the dismiss button carries the name.
        "Xóa Dat P. Nguyen",
    ],
)
def test_destructive_label_vocabulary(label: str) -> None:
    assert u2_exec_mod._fb_is_destructive_label(label) is True


@pytest.mark.parametrize(
    "label",
    [
        "Thêm bạn bè",
        "Bình luận",
        "Thích",
        # Short tokens must match as words, not as fragments of a name.
        "Gogo Nguyen",
        # Vietnamese name syllables that fold onto button words.
        "Chan Thi Mai",
        "Xoan Nguyen",
        "Go Thi Lan",
    ],
)
def test_ordinary_controls_are_not_blocked(label: str) -> None:
    assert u2_exec_mod._fb_is_destructive_label(label) is False


# ── Screens the scenario did not ask for ─────────────────────────────────────


def _screen(*labels: str, sheet: bool = False) -> str:
    nodes = [_fb_node("", bounds="[0,0][1260,2800]")]
    nodes += [
        _fb_node(label, bounds=f"[0,{100 * i}][1260,{100 * i + 80}]")
        for i, label in enumerate(labels)
    ]
    if sheet:
        # Bottom sheet: full width, anchored to the bottom, partial height.
        nodes.append(_fb_node("", bounds="[0,1900][1260,2800]"))
    return _fb_xml(*nodes)


def test_ordinary_screen_is_not_treated_as_an_anomaly() -> None:
    assert (
        u2_exec_mod._fb_classify_surface(_screen("Bạn bè", "Thêm bạn bè"))["state"]
        == u2_exec_mod.SURFACE_OK
    )


@pytest.mark.parametrize(
    "label",
    [
        "Bạn tạm thời bị chặn",
        "Xác nhận danh tính của bạn",
        "Tài khoản của bạn đã bị vô hiệu hóa",
        "Bạn đang đi quá nhanh",
    ],
)
def test_account_walls_are_never_retryable(label: str) -> None:
    """Repeating an action against a checkpoint is how a recoverable account
    becomes an unrecoverable one."""
    surface = u2_exec_mod._fb_classify_surface(_screen(label))

    assert surface["state"] == u2_exec_mod.SURFACE_BLOCKED
    assert surface["retryable"] is False


def test_a_sheet_is_dismissable_not_a_wall() -> None:
    """One Back clears it; stopping the run for it would be an overreaction."""
    surface = u2_exec_mod._fb_classify_surface(
        _screen("Tại sao tôi nhìn thấy những gợi ý kết bạn này?")
    )

    assert surface["state"] == u2_exec_mod.SURFACE_DISMISSABLE
    assert surface["retryable"] is True


def test_overlay_is_detected_by_shape_not_by_resource_id() -> None:
    """Facebook renames ids between builds; a bottom sheet is always a wide
    container anchored to the bottom edge."""
    surface = u2_exec_mod._fb_classify_surface(_screen("Bạn bè", sheet=True))

    assert surface["state"] == u2_exec_mod.SURFACE_DISMISSABLE
    assert surface["overlay_bounds"] is not None


def test_blocked_account_stops_the_friend_flow_without_tapping(monkeypatch):
    monkeypatch.setattr(u2_exec_mod.time, "sleep", lambda _seconds: None)
    blocked = _fb_xml(
        _fb_node("Bạn tạm thời bị chặn", bounds="[40,100][900,160]"),
        _fb_node("Nguyen Van A", bounds="[40,300][400,345]"),
        _fb_node("3 bạn chung", bounds="[40,346][400,390]"),
        _fb_node("Thêm bạn bè", bounds="[600,320][900,400]", clickable=True),
    )
    dev = _FlowDevice(blocked)

    result = u2_exec_mod._flow_fb_connect_visible_people(
        dev,
        {"target_count": 1, "max_scrolls": 0, "min_score": 40, "require_common": True},
    )

    assert result["reason"] == "account_blocked"
    assert result["retryable"] is False
    assert dev.clicks == []


def test_screen_fingerprint_is_stable_and_content_addressed() -> None:
    """Unknown screens are worth counting: what appears forty times deserves a
    handler, what appears once does not."""
    first = u2_exec_mod._fb_surface_fingerprint(_screen("Bạn bè", "Gợi ý"))
    same = u2_exec_mod._fb_surface_fingerprint(_screen("Gợi ý", "Bạn bè"))
    other = u2_exec_mod._fb_surface_fingerprint(_screen("Marketplace"))

    assert first == same
    assert first != other
