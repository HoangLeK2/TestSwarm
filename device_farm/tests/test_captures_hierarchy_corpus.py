"""Corpus tests over ``device_farm/captures/`` (full session tree).

- Every ``*.xml`` dump: ``fb_extract`` post/comment parse + shape checks (FB invariants).
- Every ``*.json``: valid JSON; ``*_selector.json`` matches tap-selector schema.
- Every ``*.jpg``: readable JPEG (Pillow), non-trivial dimensions — mirrors screenshot storage.

CI clones ``captures/`` or records device sessions; unknown file types fail the whitelist test.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from PIL import Image

from tasks.fb_extract import (
    _dedup,
    _expand_see_more,
    is_fb_post_truncated,
    parse_fb_comments_from_xml,
    parse_fb_posts_from_xml,
)

CAPTURES_ROOT = Path(__file__).resolve().parent.parent / "captures"
_FB_MARKER = "com.facebook.katana"


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

    def scroll(self, direction: str, distance: float, *, duration_ms: int = 400) -> None:
        self.scrolls.append((direction, distance))


_ALLOWED_CAPTURE_SUFFIXES = frozenset({".xml", ".jpg", ".json"})


def _iter_xml() -> List[Path]:
    if not CAPTURES_ROOT.is_dir():
        return []
    return sorted(CAPTURES_ROOT.rglob("*.xml"))


def _iter_json() -> List[Path]:
    if not CAPTURES_ROOT.is_dir():
        return []
    return sorted(CAPTURES_ROOT.rglob("*.json"))


def _iter_jpg() -> List[Path]:
    if not CAPTURES_ROOT.is_dir():
        return []
    return sorted(CAPTURES_ROOT.rglob("*.jpg"))


_XML_PATHS = _iter_xml()
_JSON_PATHS = _iter_json()
_JPG_PATHS = _iter_jpg()


def _rel_id(path: Path) -> str:
    return str(path.relative_to(CAPTURES_ROOT))


def _require_capture_file(path: Path) -> None:
    if not path.is_file():
        pytest.skip(f"missing golden capture {path}")


_REQUIRED_POST_KEYS = frozenset({
    "author",
    "text",
    "timestamp",
    "reactions",
    "comments",
    "shares",
    "views",
    "source_index",
    "post_type",
    "image_desc",
    "comment_preview",
    "_pid",
    "stable_post_id",
    "post_key",
    "fb_post_id",
    "fb_group_id",
    "permalink_candidates",
})


def _assert_post_shape(p: Dict[str, Any]) -> None:
    missing = _REQUIRED_POST_KEYS - p.keys()
    assert not missing, f"post missing keys {missing}: {p.keys()}"
    assert isinstance(p["author"], str)
    assert isinstance(p["text"], str)
    assert isinstance(p["timestamp"], str)
    assert isinstance(p["source_index"], int)
    assert isinstance(p["post_type"], str)
    assert p["fb_post_id"] is None or isinstance(p["fb_post_id"], str)
    assert p["fb_group_id"] is None or isinstance(p["fb_group_id"], str)
    assert isinstance(p["permalink_candidates"], list)
    assert p["image_desc"] is None or isinstance(p["image_desc"], str)
    assert p["comment_preview"] is None or isinstance(p["comment_preview"], str)
    fidx = p.get("feed_item_index")
    assert fidx is None or isinstance(fidx, int)
    ma = p.get("media_artifacts")
    if ma is not None:
        assert isinstance(ma, list)
        for item in ma:
            assert isinstance(item, dict)
            assert item.get("kind") == "carousel_photo"
            assert isinstance(item.get("slot"), int)
            assert isinstance(item.get("total"), int)
            b = item.get("bounds")
            assert b is None or (
                isinstance(b, list) and len(b) == 4 and all(isinstance(x, int) for x in b)
            )


def _assert_comment_shape(c: Dict[str, Any]) -> None:
    if c.get("_type") == "post_stats":
        assert "reactions" in c or "shares" in c
        return
    assert isinstance(c.get("author"), str)
    assert isinstance(c.get("text"), str)


@pytest.mark.parametrize("xml_path", _XML_PATHS, ids=_rel_id)
def test_capture_hierarchy_parses_without_error(xml_path: Path) -> None:
    raw = xml_path.read_bytes()
    xml = raw.decode("utf-8", errors="replace")
    posts = parse_fb_posts_from_xml(xml)
    comments = parse_fb_comments_from_xml(xml)
    assert isinstance(posts, list)
    assert isinstance(comments, list)
    for p in posts:
        _assert_post_shape(p)
    for c in comments:
        _assert_comment_shape(c)

    if _FB_MARKER not in xml:
        return
    for p in posts:
        tl = (p.get("text") or "").lower()
        if "xem thêm" in tl or "see more" in tl:
            assert is_fb_post_truncated(p), f"{_rel_id(xml_path)}: body mentions expand phrase but not truncated"
        ma = p.get("media_artifacts") or []
        if ma:
            totals = {a["total"] for a in ma}
            assert len(totals) == 1, f"{_rel_id(xml_path)}: mixed carousel totals {totals}"
            t0 = next(iter(totals))
            for a in ma:
                assert 1 <= a["slot"] <= t0, f"{_rel_id(xml_path)}: bad slot {a}"
        if len(p.get("text") or "") > 15:
            assert p.get("stable_post_id"), f"{_rel_id(xml_path)}: missing stable_post_id"
            assert p.get("post_key"), f"{_rel_id(xml_path)}: missing post_key"


def test_captures_corpus_nonempty() -> None:
    assert len(_XML_PATHS) > 100, (
        "expected device_farm/captures/**/*.xml — clone captures or run device sessions"
    )
    assert len(_JPG_PATHS) > 100, "expected screenshot *.jpg alongside hierarchy dumps"
    assert len(_JSON_PATHS) >= 5, "expected tap_selector *.json sidecars in sessions"


def test_captures_only_whitelisted_file_types() -> None:
    """Reject stray binaries (e.g. .png, .DS_Store) so artifact layout stays production-safe."""
    if not CAPTURES_ROOT.is_dir():
        pytest.skip("no captures tree")
    bad: List[str] = []
    for p in CAPTURES_ROOT.rglob("*"):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf not in _ALLOWED_CAPTURE_SUFFIXES:
            bad.append(_rel_id(p))
    assert not bad, f"unexpected capture file types: {bad[:20]}{'…' if len(bad) > 20 else ''}"


@pytest.mark.parametrize("json_path", _JSON_PATHS, ids=_rel_id)
def test_capture_json_loads_and_selector_shape(json_path: Path) -> None:
    raw = json_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict)
    if json_path.name.endswith("_selector.json"):
        assert isinstance(data.get("by"), str) and data["by"]
        assert "value" in data and isinstance(data["value"], str)


@pytest.mark.parametrize("jpg_path", _JPG_PATHS, ids=_rel_id)
def test_capture_jpg_readable(jpg_path: Path) -> None:
    if jpg_path.stat().st_size <= 32:
        if os.getenv("ALLOW_TINY_CAPTURE_ARTIFACTS") == "1":
            # Active local sessions can transiently leave tiny placeholder files.
            pytest.skip(f"skip tiny/incomplete capture artifact {_rel_id(jpg_path)}")
        pytest.fail(f"tiny/incomplete capture artifact {_rel_id(jpg_path)}")
    with Image.open(jpg_path) as im:
        im.verify()
    with Image.open(jpg_path) as im:
        im.load()
        w, h = im.size
        assert w >= 1 and h >= 1, f"invalid dimensions {_rel_id(jpg_path)} {w}x{h}"
        # Full screenshots are large; element crops can be thin strips (e.g. one UI row).
        assert w * h >= 64, f"suspiciously tiny bitmap {_rel_id(jpg_path)} {w}x{h}"


def test_golden_171541_scroll_no_toolbar_chrome_as_comments() -> None:
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_171541"
        / "step_000_scroll_down_hierarchy.xml"
    )
    _require_capture_file(path)
    rows = parse_fb_comments_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    joined = " ".join(
        f"{c.get('author', '')} {c.get('text', '')}"
        for c in rows
        if c.get("_type") != "post_stats"
    ).lower()
    assert "tìm kiếm trong" not in joined
    assert "công cụ khác cho thành viên" not in joined
    assert "lựa chọn khác cho bài viết" not in joined


def test_golden_181441_feed_comment_stays_in_same_recycler_card() -> None:
    """Feed: một comment preview + bài kế tiếp — không parse caption bài sau thành comment."""
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_181441"
        / "step_000_scroll_down_hierarchy.xml"
    )
    _require_capture_file(path)
    rows = parse_fb_comments_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    body = [c for c in rows if c.get("_type") != "post_stats"]
    joined = " ".join(
        f"{c.get('author', '')} {c.get('text', '')}" for c in body
    )
    assert "Một repo đang hot" not in joined
    assert "openclaw" not in joined.lower()
    but = next((c for c in body if (c.get("author") or "").strip().startswith("But")), None)
    assert but is not None
    assert len((but.get("text") or "").strip()) >= 20


def test_golden_172100_feed_two_posts_open_claw_and_carousel() -> None:
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_172100"
        / "step_001_extract_pre_hierarchy.xml"
    )
    _require_capture_file(path)
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert len(posts) >= 2
    phan = next((p for p in posts if p.get("author") == "Phan Đình Long"), None)
    assert phan is not None
    assert "Open Claw" in (phan.get("text") or "")
    assert phan.get("feed_item_index") == 0
    le = next((p for p in posts if p.get("author") == "Lê Phan Trường Giang"), None)
    assert le is not None
    assert "Hỏi Nhanh" in (le.get("text") or "") or "Xem thêm" in (le.get("text") or "")
    arts = le.get("media_artifacts") or []
    assert len(arts) == 3
    assert [a["slot"] for a in arts] == [1, 2, 3]
    assert le.get("feed_item_index") == 1
    assert le.get("post_type") == "photo"


def test_golden_171940_comment_thread_many_rows() -> None:
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_171940"
        / "step_002_scroll_down_hierarchy.xml"
    )
    _require_capture_file(path)
    rows = parse_fb_comments_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    body = [c for c in rows if c.get("_type") != "post_stats"]
    assert len(body) >= 5
    stats = next((c for c in rows if c.get("_type") == "post_stats"), None)
    assert stats is not None
    assert stats.get("reactions") == "60"
    assert stats.get("shares") == "33"


def test_golden_171900_truncated_lead_post_four_carousel_slots() -> None:
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_171900"
        / "step_004_scroll_down_hierarchy.xml"
    )
    _require_capture_file(path)
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert len(posts) >= 2
    lead = posts[0]
    assert "TỰ ĐỘNG TÌM LEAD" in (lead.get("text") or "")
    assert is_fb_post_truncated(lead)
    arts = lead.get("media_artifacts") or []
    assert len(arts) == 4
    assert [a["slot"] for a in arts] == [1, 2, 3, 4]
    assert {a["total"] for a in arts} == {4}
    assert lead.get("feed_item_index") == 0
    second = next((p for p in posts if p.get("author") == "Mai Gia"), None)
    assert second is not None
    assert "openclaw" in (second.get("text") or "").lower()


def test_golden_171917_comment_thread_many_rows() -> None:
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_171917"
        / "step_000_extract_hierarchy.xml"
    )
    _require_capture_file(path)
    rows = parse_fb_comments_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    body = [c for c in rows if c.get("_type") != "post_stats"]
    # Sau khi lọc hàng chỉ còn tên tắt (body rỗng) / rác UI, số dòng giảm; giữ ngưỡng thấp + invariant chất lượng.
    assert len(body) >= 8
    stats = next((c for c in rows if c.get("_type") == "post_stats"), None)
    assert stats is not None
    assert stats.get("reactions") == "60"
    assert stats.get("shares") == "33"


def test_dedup_merges_consecutive_scroll_frames_171900() -> None:
    root = CAPTURES_ROOT / "49c62ff79ec0c35d_2026-04-12_171900"
    p1 = root / "step_001_extract_hierarchy.xml"
    p2 = root / "step_004_scroll_down_hierarchy.xml"
    _require_capture_file(p1)
    _require_capture_file(p2)
    a = parse_fb_posts_from_xml(p1.read_text(encoding="utf-8", errors="replace"))
    b = parse_fb_posts_from_xml(p2.read_text(encoding="utf-8", errors="replace"))
    merged = _dedup(a + b)
    assert 1 <= len(merged) <= len(a) + len(b)


@patch("tasks.fb_extract.time.sleep", lambda *_a, **_k: None)
def test_expand_see_more_taps_visible_xem_them_on_171900_capture() -> None:
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-12_171900"
        / "step_004_scroll_down_hierarchy.xml"
    )
    _require_capture_file(path)
    xml_before = path.read_text(encoding="utf-8", errors="replace")
    xml_after = xml_before.replace("Xem thêm", "")
    dev = _FakeDevice([xml_before, xml_after, xml_after, xml_after])
    n = _expand_see_more(dev, max_passes=5, scroll_between=False, no_change_threshold=3)
    assert n >= 1
    assert len(dev.taps) >= 1


def test_golden_221514_does_not_collapse_body_to_image_label() -> None:
    """Profile tab-strip + stale action row should not force post text to bare 'Ảnh'."""
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-29_221514"
        / "step_000_extract_pre_hierarchy.xml"
    )
    _require_capture_file(path)
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert posts
    lead = posts[0]
    assert lead.get("author") == "M-TP"
    assert (lead.get("text") or "").strip().lower() != "ảnh"
    assert "ĐỪNG LÀM TRÁI TIM ANH ĐAU" in (lead.get("text") or "")


def test_golden_224209_profile_post_keeps_author_and_strips_pinned_header_from_body() -> None:
    """Pinned metadata row must stay out of body; author should not collapse to media label."""
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-29_224209"
        / "step_000_extract_pre_hierarchy.xml"
    )
    _require_capture_file(path)
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert posts
    lead = posts[0]
    assert lead.get("author") == "Hoàng Minh Châu"
    text = (lead.get("text") or "")
    assert "Bài viết đã ghimĐã ghim" not in text
    assert "Chia sẻ với: Công khai" not in text
    assert "Việt Nam tôi đó" in text


def test_golden_225853_extracts_primary_post_and_skips_footer_hide_row() -> None:
    """Event/ad style card should parse as one post; trailing footer row is junk."""
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-29_225853"
        / "step_000_extract_pre_hierarchy.xml"
    )
    _require_capture_file(path)
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert len(posts) == 1
    lead = posts[0]
    assert lead.get("author") == "Triển lãm Điện tử & Thiết bị thông minh tại Việt Nam"
    assert "NGUỒN HÀNG ĐIỆN TỬ HỘI TỤ" in (lead.get("text") or "")
    assert (lead.get("timestamp") or "") == ""


def test_golden_230946_expanded_sheet_still_extracts_post() -> None:
    """After tapping 'Xem thêm', expanded sheet layout must still yield a post."""
    path = (
        CAPTURES_ROOT
        / "49c62ff79ec0c35d_2026-04-29_230946"
        / "step_000_extract_hierarchy.xml"
    )
    _require_capture_file(path)
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert posts
    lead = posts[0]
    assert lead.get("author") == "Triển lãm Điện tử & Thiết bị thông minh tại Việt Nam"
    assert "Bạn không cần tìm kiếm nhiều nơi vì IEAE Vietnam 2026" in (lead.get("text") or "")
