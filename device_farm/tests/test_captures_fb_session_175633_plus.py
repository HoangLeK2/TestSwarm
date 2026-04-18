"""Goldens + invariants for FB hierarchy dumps in sessions ``49c62ff79ec0c35d_2026-04-12_*`` from 175633 onward.

- **Invariant** (auto): mọi ``*_pre_hierarchy.xml`` có Facebook trong session suffix ≥ ``175633`` —
  thân bài dài không được dính chuỗi toolbar (regression post-detail / feed cluster).
- **Goldens** (thủ công): thêm tuple vào ``_FEED_TWO_CARD_PATHS`` / ``_VIET_TUNG_LONG_PATHS`` hoặc
  hàm ``test_golden_*`` khi có capture mới cùng kiểu UI.

Khi thêm session mới chỉ cần copy capture; invariant chạy tự động. Khi có layout mới cần kỳ vọng
cụ thể (author, comment, stats) — bổ sung golden.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

import pytest

from tasks.fb_extract import (
    is_fb_post_truncated,
    parse_fb_comments_from_xml,
    parse_fb_posts_from_xml,
)

CAPTURES = Path(__file__).resolve().parent.parent / "captures"
_SESSION_PREFIX = "49c62ff79ec0c35d_2026-04-12_"
_MIN_SESSION_SUFFIX = "175633"
_FB_PKG = "com.facebook.katana"

# Chuỗi từng bị merge nhầm vào "post" khi cluster sai (toolbar + post-detail).
_TOOLBAR_JUNK_IN_BODY = (
    "Quay lại",
    "Tìm kiếm trong OpenClaw",
)


def _session_suffix(dir_name: str) -> str:
    return dir_name.split("_")[-1]


def _iter_fb_pre_hierarchy_xml_since() -> Iterable[Path]:
    if not CAPTURES.is_dir():
        return
    for d in sorted(CAPTURES.glob(f"{_SESSION_PREFIX}*")):
        if not d.is_dir() or _session_suffix(d.name) < _MIN_SESSION_SUFFIX:
            continue
        for p in sorted(d.glob("*_pre_hierarchy.xml")):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:12_000]
            except OSError:
                continue
            if _FB_PKG in head:
                yield p


def _rel(p: Path) -> str:
    return str(p.relative_to(CAPTURES))


_FB_PRE_XML_PATHS: List[Path] = sorted(
    _iter_fb_pre_hierarchy_xml_since(),
    key=lambda x: str(x),
)


@pytest.mark.parametrize("xml_path", _FB_PRE_XML_PATHS, ids=_rel)
def test_fb_pre_hierarchy_since_175633_no_toolbar_junk_in_long_bodies(xml_path: Path) -> None:
    """Mọi bài có text đủ dài không được chứa label toolbar (lỗi cluster post-detail)."""
    xml = xml_path.read_text(encoding="utf-8", errors="replace")
    posts = parse_fb_posts_from_xml(xml)
    for p in posts:
        t = p.get("text") or ""
        if len(t) <= 100:
            continue
        for phrase in _TOOLBAR_JUNK_IN_BODY:
            assert phrase not in t, f"{_rel(xml_path)}: {phrase!r} in post body (len={len(t)})"


def test_fb_pre_hierarchy_since_175633_corpus_nonempty() -> None:
    if not _FB_PRE_XML_PATHS and os.getenv("ALLOW_MISSING_CAPTURE_CORPUS") == "1":
        pytest.skip("session 175633+ capture corpus not available on this machine")
    assert len(_FB_PRE_XML_PATHS) >= 10, (
        "expected device_farm/captures/49c62ff79ec0c35d_2026-04-12_*/*_pre_hierarchy.xml "
        f"with {_FB_PKG} from session {_MIN_SESSION_SUFFIX}+"
    )


def test_golden_175633_post_detail_long_body_single_row() -> None:
    """Một RecyclerView child: bài dài + cụm '1 tuần' trong prose không cắt body."""
    path = CAPTURES / "49c62ff79ec0c35d_2026-04-12_175633/step_000_wait_pre_hierarchy.xml"
    if not path.is_file():
        pytest.skip("capture 175633 missing")
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert len(posts) == 1, [p.get("author") for p in posts]
    txt = posts[0].get("text") or ""
    assert len(txt) > 500
    assert "OpenClawSetup" in txt or "#OpenClawSetup" in txt
    assert "9Router" in txt or "9ROUTER" in txt.upper()
    for phrase in _TOOLBAR_JUNK_IN_BODY:
        assert phrase not in txt
    assert not is_fb_post_truncated(posts[0])


@pytest.mark.parametrize(
    "rel",
    (
        "49c62ff79ec0c35d_2026-04-12_175848/step_000_wait_pre_hierarchy.xml",
        "49c62ff79ec0c35d_2026-04-12_175959/step_000_scroll_down_pre_hierarchy.xml",
    ),
    ids=lambda s: s.split("/")[-2] + "/" + s.split("/")[-1],
)
def test_golden_feed_truncated_comment_row_plus_gmvmax_and_fomo_posts(rel: str) -> None:
    """Hàng đầu là comment preview (Xem thêm); dưới là 2 bài Nguyễn Tá Thuật + Viết Tùng."""
    path = CAPTURES / rel
    if not path.is_file():
        pytest.skip(f"missing {rel}")
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    by_author = {p.get("author"): p for p in posts}
    ntt = by_author.get("Nguyễn Tá Thuật")
    assert ntt is not None, f"authors={list(by_author)}"
    assert "gmvmax" in (ntt.get("text") or "").lower()
    vt = by_author.get("Viết Tùng")
    assert vt is not None
    assert "fomo" in (vt.get("text") or "").lower()


@pytest.mark.parametrize(
    "rel",
    (
        "49c62ff79ec0c35d_2026-04-12_180001/step_000_wait_pre_hierarchy.xml",
        "49c62ff79ec0c35d_2026-04-12_180002/step_000_dismiss_popup_pre_hierarchy.xml",
        "49c62ff79ec0c35d_2026-04-12_180005/step_000_wait_pre_hierarchy.xml",
    ),
    ids=lambda s: s.split("/")[-2],
)
def test_golden_late_session_viet_tung_long_body(rel: str) -> None:
    """Feed/card: bài thứ hai Viết Tùng — body dài đủ (sau scroll / popup)."""
    path = CAPTURES / rel
    if not path.is_file():
        pytest.skip(f"missing {rel}")
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    vt = next((p for p in posts if p.get("author") == "Viết Tùng"), None)
    assert vt is not None, [p.get("author") for p in posts]
    txt = vt.get("text") or ""
    assert len(txt) >= 200
    assert "fomo" in txt.lower()


def test_golden_175839_comment_sheet_reactions_and_tran_reply() -> None:
    """Sheet phản hồi: stats header + ít nhất một comment có nội dung kỹ thuật."""
    path = CAPTURES / "49c62ff79ec0c35d_2026-04-12_175839/step_000_scroll_down_pre_hierarchy.xml"
    if not path.is_file():
        pytest.skip("capture 175839 missing")
    xml = path.read_text(encoding="utf-8", errors="replace")
    rows = parse_fb_comments_from_xml(xml)
    stats = next((c for c in rows if c.get("_type") == "post_stats"), None)
    assert stats is not None
    assert stats.get("reactions") == "65"
    assert stats.get("shares") == "11"
    bodies = [c for c in rows if c.get("_type") != "post_stats"]
    assert any(
        c.get("author") == "Trần Văn Thành" and "design system" in (c.get("text") or "").lower()
        for c in bodies
    ), [(c.get("author"), (c.get("text") or "")[:40]) for c in bodies[:8]]


def test_golden_175839_comment_sheet_yields_no_group_posts() -> None:
    """Sheet có nút Đóng + RecyclerView thấp — không coi thread là feed post (Trần chỉ qua comments)."""
    path = CAPTURES / "49c62ff79ec0c35d_2026-04-12_175839/step_000_scroll_down_pre_hierarchy.xml"
    if not path.is_file():
        pytest.skip("capture 175839 missing")
    posts = parse_fb_posts_from_xml(path.read_text(encoding="utf-8", errors="replace"))
    assert posts == []
