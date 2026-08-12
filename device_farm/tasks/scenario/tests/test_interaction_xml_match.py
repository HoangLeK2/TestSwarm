from __future__ import annotations

from tasks.scenario.context import ScenarioContext
from tasks.scenario.steps.interaction import handle_tap_xml_match


class _Device:
    serial = "serial-1"
    model = "test"
    screen_width = 1260
    screen_height = 2800

    def __init__(self, xml: str) -> None:
        self.xml = xml
        self.taps: list[tuple[int, int]] = []

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return self.xml

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))


def _ctx(device: _Device) -> ScenarioContext:
    return ScenarioContext.from_args(device, {"steps": []})


def test_tap_xml_match_taps_center_of_clickable_content_desc_match() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy>
      <node class="android.widget.Button"
            content-desc="Go2Joy Vietnam đã xác minh"
            clickable="true"
            bounds="[14,491][1246,757]" />
    </hierarchy>
    """
    device = _Device(xml)
    result = {"ok": True}

    handle_tap_xml_match(
        _ctx(device),
        {
            "type": "tap_xml_match",
            "attr": "content-desc",
            "contains": "Go2Joy Vietnam",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
        result,
    )

    assert result["ok"] is True
    assert device.taps == [(630, 624)]
    assert result["_bounds"] == {"left": 14, "top": 491, "right": 1246, "bottom": 757}


def test_tap_xml_match_fails_when_no_clickable_match() -> None:
    device = _Device('<hierarchy><node content-desc="Go2Joy Vietnam" clickable="false" bounds="[0,0][10,10]" /></hierarchy>')
    result = {"ok": True}

    handle_tap_xml_match(
        _ctx(device),
        {
            "type": "tap_xml_match",
            "attr": "content-desc",
            "contains": "Go2Joy Vietnam",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
        result,
    )

    assert result["ok"] is False
    assert device.taps == []
    assert "not found" in result["message"]
