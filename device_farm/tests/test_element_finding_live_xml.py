"""Element-finding tests against live hierarchy dumps (refresh via MCP df_hierarchy)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from runtime.core.device_client import DeviceClient

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "element_finding"
_LIVE_FIXTURE = _FIXTURE_DIR / "facebook_codex_vn_live.xml"

# Vivo V2352A — dump captured via MCP df_hierarchy on Codex VN group feed.
_SCREEN_W = 1260
_SCREEN_H = 2737


def _load_live_xml() -> str:
    if not _LIVE_FIXTURE.is_file():
        pytest.skip(
            f"missing {_LIVE_FIXTURE.name}; refresh with MCP df_hierarchy "
            f"device=10AE7S00HD002JK refresh=true"
        )
    return _LIVE_FIXTURE.read_text(encoding="utf-8")


def _device_with_xml(xml: str) -> DeviceClient:
    device = DeviceClient.__new__(DeviceClient)
    device.hierarchy_xml = Mock(side_effect=lambda force_refresh=False: xml)
    device.screen_width = _SCREEN_W
    device.screen_height = _SCREEN_H
    return device


@pytest.mark.parametrize(
    ("x", "y", "expected_by", "expected_value"),
    [
        # Post action bar — must open comment sheet, not group header / profile.
        (310, 1069, "description", "Bình luận"),
        # Group title in chrome — only when tapping the header strip.
        (356, 212, "description", "Codex VN"),
        # Comment author row — semantic name (opens profile if executed).
        (486, 1467, "description", "Người tham gia ẩn danh 175"),
    ],
)
def test_hit_test_live_codex_vn_feed(
    x: int, y: int, expected_by: str, expected_value: str
) -> None:
    xml = _load_live_xml()
    device = _device_with_xml(xml)

    sel = device.hit_test_selector(x, y)

    assert sel is not None
    assert sel["by"] == expected_by
    assert sel["value"] == expected_value


def test_hit_test_live_comment_not_group_header() -> None:
    xml = _load_live_xml()
    device = _device_with_xml(xml)

    sel = device.hit_test_selector(310, 1069)

    assert sel is not None
    assert sel["value"] != "Codex VN"
    assert "thành viên" not in (sel.get("value") or "").lower()
