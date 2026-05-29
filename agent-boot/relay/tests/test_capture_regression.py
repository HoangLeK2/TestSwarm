"""Regression tests against real device_farm/captures hierarchy dumps."""
from __future__ import annotations

from pathlib import Path

import pytest

from relay.extra_data.ingest import _parse_items
from relay.extra_data.parsers.facebook import (
    parse_fb_comments_from_xml_with_diagnostic,
    parse_fb_posts_from_xml_with_diagnostic,
    resolve_comment_targets_from_xml,
)
from relay.extra_data.parsers.facebook.parser import _hierarchy_is_fb_comment_sheet, _parse_xml

_CAPTURES_ROOT = Path(__file__).resolve().parents[3] / "device_farm" / "captures"

_COMMENT_SHEET_CAPTURE = (
    _CAPTURES_ROOT / "10AE7S00HD002JK_2026-05-28_231850" / "step_000_tap_fb_comment_button_hierarchy.xml"
)
_FEED_INLINE_CAPTURE = (
    _CAPTURES_ROOT / "10AE7S00HD002JK_2026-05-28_231945" / "step_000_tap_fb_comment_button_hierarchy.xml"
)
_FEED_INLINE_THREAD_CAPTURE = (
    _CAPTURES_ROOT / "10AE7S00HD002JK_2026-05-28_232350" / "step_000_tap_fb_comment_button_hierarchy.xml"
)


def _hierarchy_files() -> list[Path]:
    if not _CAPTURES_ROOT.is_dir():
        return []
    return sorted(
        p
        for p in _CAPTURES_ROOT.rglob("*_hierarchy.xml")
        if "pre_" not in p.name
    )


@pytest.mark.skipif(not _COMMENT_SHEET_CAPTURE.is_file(), reason="local capture fixture missing")
def test_vivo_comment_sheet_parses_five_comments() -> None:
    xml = _COMMENT_SHEET_CAPTURE.read_text(encoding="utf-8")
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id="capture-test")
    assert diag["reason_code"] == "ok"
    assert diag.get("parse_mode") == "comment_sheet"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert len(bodies) >= 5


@pytest.mark.skipif(not _FEED_INLINE_CAPTURE.is_file(), reason="local capture fixture missing")
def test_feed_inline_comments_when_sheet_not_open() -> None:
    xml = _FEED_INLINE_CAPTURE.read_text(encoding="utf-8")
    root = _parse_xml(xml)
    assert root is not None
    assert _hierarchy_is_fb_comment_sheet(root) is False

    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id=None)
    assert diag["reason_code"] == "ok"
    assert diag.get("parse_mode") == "feed_inline"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert len(bodies) >= 1
    assert any("Hoàng" in str(r.get("author") or "") for r in bodies)


@pytest.mark.skipif(not _FEED_INLINE_THREAD_CAPTURE.is_file(), reason="local capture fixture missing")
def test_feed_inline_thread_without_pid_can_include_highlighted_parent() -> None:
    """Unscoped parse may include pinned parent-thread rows above the card."""
    xml = _FEED_INLINE_THREAD_CAPTURE.read_text(encoding="utf-8")
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id=None)
    assert diag["reason_code"] == "ok"
    assert diag.get("parse_mode") == "feed_inline"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert len(bodies) >= 2
    authors = {str(r.get("author") or "") for r in bodies}
    assert any("Flex" in a for a in authors)
    assert any("Hoàng" in a for a in authors)


@pytest.mark.skipif(not _FEED_INLINE_THREAD_CAPTURE.is_file(), reason="local capture fixture missing")
def test_feed_inline_scoped_to_tapped_post_excludes_parent_thread() -> None:
    xml = _FEED_INLINE_THREAD_CAPTURE.read_text(encoding="utf-8")
    top, _ = resolve_comment_targets_from_xml(xml)
    assert top is not None
    tap_pid = top["post"]["_pid"]
    assert tap_pid

    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id=tap_pid)
    assert diag["reason_code"] == "ok"
    assert diag.get("parse_mode") == "feed_inline"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert len(bodies) == 1
    assert all(r.get("parent_post_id") == tap_pid for r in bodies)
    assert "Hoàng" in str(bodies[0].get("author") or "")
    assert not any("Flex" in str(r.get("author") or "") for r in bodies)


@pytest.mark.skipif(not _FEED_INLINE_CAPTURE.is_file(), reason="local capture fixture missing")
def test_feed_inline_tap_target_matches_visible_inline_comment_post() -> None:
    xml = _FEED_INLINE_CAPTURE.read_text(encoding="utf-8")
    _, ingest_diag = _parse_items("fb_comment_target", xml, {})
    assert ingest_diag["reason_code"] == "ok"
    tap_pid = ingest_diag["target"]["pid"]

    posts, _ = parse_fb_posts_from_xml_with_diagnostic(xml, 0)
    posts = [p for p in posts if p.get("_type") != "post_stats"]
    tapped = next(p for p in posts if p.get("_pid") == tap_pid)

    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id=tap_pid)
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert diag["reason_code"] == "ok"
    assert len(bodies) >= 1
    assert all(r.get("parent_post_id") == tap_pid for r in bodies)
    assert "telegram" in str(tapped.get("text") or "").lower()
    assert "telegram" in str(bodies[0].get("text") or "").lower() or "gofile" in str(bodies[0].get("text") or "").lower()


@pytest.mark.parametrize("capture_path", _hierarchy_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_capture_posts_parse_or_expected_skip(capture_path: Path) -> None:
    xml = capture_path.read_text(encoding="utf-8")
    rows, diag = parse_fb_posts_from_xml_with_diagnostic(xml, 0)
    reason = diag.get("reason_code")
    posts = [r for r in rows if isinstance(r, dict) and r.get("_type") != "post_stats"]

    if reason == "comment_sheet_no_posts_expected":
        assert len(posts) == 0
        return
    assert reason == "ok", f"{capture_path}: {reason}"
    assert len(posts) >= 1, capture_path


@pytest.mark.parametrize("capture_path", _hierarchy_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_capture_comments_when_sheet_or_inline(capture_path: Path) -> None:
    xml = capture_path.read_text(encoding="utf-8")
    root = _parse_xml(xml)
    if root is None:
        pytest.skip("unparseable xml")

    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id="capture-test")
    reason = diag.get("reason_code")
    bodies = [r for r in rows if r.get("_type") != "post_stats"]

    if _hierarchy_is_fb_comment_sheet(root):
        assert reason == "ok", capture_path
        assert len(bodies) >= 1, capture_path
        return

    if reason == "ok":
        assert diag.get("parse_mode") == "feed_inline"
        assert len(bodies) >= 1, capture_path
        return

    assert reason == "not_comment_sheet", capture_path
