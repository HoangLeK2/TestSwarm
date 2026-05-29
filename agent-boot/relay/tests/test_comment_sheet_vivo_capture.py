"""Regression: Vivo/hierarchy dumps often omit scrollable=true on RecyclerView."""
from __future__ import annotations

from pathlib import Path

import pytest

from relay.extra_data.parsers.facebook import parse_fb_comments_from_xml_with_diagnostic
from relay.extra_data.parsers.facebook.comment_pipeline import resolve_comment_scroll_swipe_from_xml
from relay.extra_data.parsers.facebook.parser import _hierarchy_is_fb_comment_sheet, _parse_xml

_CAPTURE = (
    Path(__file__).resolve().parents[3]
    / "device_farm"
    / "captures"
    / "10AE7S00HD002JK_2026-05-28_231850"
    / "step_000_tap_fb_comment_button_hierarchy.xml"
)


@pytest.mark.skipif(not _CAPTURE.is_file(), reason="local capture fixture missing")
def test_vivo_capture_detected_as_comment_sheet() -> None:
    xml = _CAPTURE.read_text(encoding="utf-8")
    root = _parse_xml(xml)
    assert root is not None
    assert _hierarchy_is_fb_comment_sheet(root) is True


@pytest.mark.skipif(not _CAPTURE.is_file(), reason="local capture fixture missing")
def test_vivo_capture_parses_multiple_comments() -> None:
    xml = _CAPTURE.read_text(encoding="utf-8")
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id="capture-test")
    assert diag["reason_code"] == "ok"
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert len(bodies) >= 5
    authors = {str(r.get("author") or "") for r in bodies}
    assert any("Flex" in a for a in authors)
    assert any("Danielle" in a for a in authors)
    assert any("Kim Anh" in a for a in authors)


@pytest.mark.skipif(not _CAPTURE.is_file(), reason="local capture fixture missing")
def test_vivo_capture_resolves_recycler_swipe_without_scrollable_attr() -> None:
    xml = _CAPTURE.read_text(encoding="utf-8")
    swipe = resolve_comment_scroll_swipe_from_xml(xml, distance_ratio=0.72)
    assert swipe is not None
    fx, fy, tx, ty = swipe
    assert ty < fy
    assert 300 < fy < 2625
