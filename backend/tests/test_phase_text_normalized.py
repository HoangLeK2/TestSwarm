"""phase_text_normalized — whitespace-tolerant rescue for text selectors.

Instagram emits NBSP (U+00A0) inside group names; UiSelector compares byte-exact
on the device, so the selector misses and burns the whole implicit wait. These
tests pin both directions of the mismatch and the refusal on ambiguity.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from runtime.element_resolver import phase_text_normalized
from services.scenario_selector import normalize_match_text

NBSP = " "
PLAIN = "OpenClaw VN · Truy cập"
WITH_NBSP = f"OpenClaw VN{NBSP}· Truy cập"


def _device(xml: str):
    dev = MagicMock()
    dev.hierarchy_xml.return_value = xml
    return dev


def _hierarchy(*nodes: str) -> str:
    return "<hierarchy>" + "".join(nodes) + "</hierarchy>"


def _node(text: str, bounds: str = "[10,20][110,60]", attr: str = "text") -> str:
    return f'<node {attr}="{text}" bounds="{bounds}"/>'


class TestNormalizeMatchText:
    def test_nbsp_collapses_to_space(self):
        assert normalize_match_text(WITH_NBSP) == PLAIN

    def test_keeps_case_and_diacritics(self):
        # accent folding would give "truy cap" — far too wide for a selector.
        assert normalize_match_text("Truy cập") == "Truy cập"

    def test_collapses_runs_and_strips(self):
        assert normalize_match_text("  a \t\n b  ") == "a b"

    def test_empty(self):
        assert normalize_match_text(None) == ""


class TestPhaseTextNormalized:
    def test_device_has_nbsp_selector_plain(self):
        dev = _device(_hierarchy(_node(WITH_NBSP)))
        r = phase_text_normalized(dev, "text", PLAIN, 1080, 1920)
        assert r is not None and r.hit
        assert (r.x, r.y) == (60, 40)
        assert r.method == "text_normalized"

    def test_device_plain_selector_has_nbsp(self):
        dev = _device(_hierarchy(_node(PLAIN)))
        r = phase_text_normalized(dev, "text", WITH_NBSP, 1080, 1920)
        assert r is not None and r.hit

    def test_matches_content_desc(self):
        dev = _device(_hierarchy(_node(WITH_NBSP, attr="content-desc")))
        r = phase_text_normalized(dev, "description", PLAIN, 1080, 1920)
        assert r is not None and r.hit

    def test_two_distinct_matches_refuses(self):
        dev = _device(_hierarchy(
            _node(WITH_NBSP, "[0,0][100,50]"),
            _node(WITH_NBSP, "[0,200][100,250]"),
        ))
        assert phase_text_normalized(dev, "text", PLAIN, 1080, 1920) is None

    def test_wrapper_and_child_are_one_element(self):
        # Same string on a clickable wrapper and its TextView — not ambiguous.
        dev = _device(_hierarchy(
            _node(WITH_NBSP, "[0,0][200,100]"),
            _node(WITH_NBSP, "[10,10][190,90]"),
        ))
        r = phase_text_normalized(dev, "text", PLAIN, 1080, 1920)
        assert r is not None and r.bounds == {
            "left": 10, "top": 10, "right": 190, "bottom": 90,
        }

    def test_exact_match_left_to_phase_selector(self):
        # phase_selector already saw this node and declined it (moved out of the
        # recorded hint); this phase must not launder that refusal.
        dev = _device(_hierarchy(_node(PLAIN)))
        assert phase_text_normalized(dev, "text", PLAIN, 1080, 1920) is None

    def test_skips_non_text_selectors(self):
        dev = _device(_hierarchy(_node(WITH_NBSP)))
        assert phase_text_normalized(dev, "resource-id", PLAIN, 1080, 1920) is None
        dev.hierarchy_xml.assert_not_called()  # no dump wasted

    def test_no_match(self):
        dev = _device(_hierarchy(_node("Something else")))
        assert phase_text_normalized(dev, "text", PLAIN, 1080, 1920) is None

    def test_empty_hierarchy(self):
        assert phase_text_normalized(_device(""), "text", PLAIN, 1080, 1920) is None

    def test_malformed_xml_does_not_raise(self):
        assert phase_text_normalized(_device("<bad"), "text", PLAIN, 1080, 1920) is None
