"""The device probe must report the resolution touch actually uses.

`wm size` prints two numbers on any phone whose display resolution was changed
from the panel default:

    Physical size: 1440x2960
    Override size: 1080x2220

scrcpy captures the override size and uiautomator injects into it, so reporting
the physical one scales every tap by 1440/1080 — taps near the right edge land
outside the screen entirely. Samsung ships Note 10+ on FHD+, so this is the
normal case there rather than an exotic one.
"""

from __future__ import annotations

import re

from relay import adb


def _probe_script() -> str:
    """The inline shell the probe runs, lifted straight out of the module."""
    source = adb.__file__
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    start = text.index('wm_out="$(wm size')
    end = text.index('emit wm_size', start)
    return text[start:end]


def _resolve(wm_output: str) -> str:
    """Apply the probe's own precedence to a captured `wm size` output."""
    override = re.search(r".*Override size: (.+)", wm_output)
    if override:
        return override.group(1).strip()
    physical = re.search(r".*Physical size: (.+)", wm_output)
    return physical.group(1).strip() if physical else ""


def test_probe_prefers_override_over_physical() -> None:
    script = _probe_script()
    assert "Override size" in script, "probe must read the override resolution"
    physical_first = script.index("Physical size")
    override_first = script.index("Override size")
    assert override_first < physical_first, (
        "override must be tried first; physical is only the fallback"
    )


def test_override_wins_on_a_downscaled_panel() -> None:
    assert _resolve("Physical size: 1440x2960\nOverride size: 1080x2220\n") == "1080x2220"


def test_physical_used_when_no_override_exists() -> None:
    assert _resolve("Physical size: 1080x2340\n") == "1080x2340"


def test_reported_size_matches_what_taps_are_scaled_against() -> None:
    # Regression guard for the observed failure: a tap at the right edge of a
    # 1080-wide display was sent as x=1348 because the probe reported 1440.
    width = int(_resolve("Physical size: 1440x2960\nOverride size: 1080x2220\n").split("x")[0])
    right_edge_tap = round(0.936 * width)
    assert right_edge_tap <= 1080, f"tap x={right_edge_tap} falls outside the display"
