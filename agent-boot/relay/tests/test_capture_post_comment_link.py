"""100% capture replay: every comment row must map to the correct parent post."""
from __future__ import annotations

from pathlib import Path

import pytest

from relay.extra_data.capture_post_comment_verify import (
    _hierarchy_paths,
    summarize_results,
    verify_all_captures,
    verify_capture_file,
    resolve_session_tap_parent_pid,
)
from relay.extra_data.parsers.facebook import parse_fb_comments_from_xml_with_diagnostic

_CAPTURES_ROOT = Path(__file__).resolve().parents[3] / "device_farm" / "captures"


def _all_capture_paths() -> list[Path]:
    if not _CAPTURES_ROOT.is_dir():
        return []
    paths: list[Path] = []
    for session_dir in sorted(_CAPTURES_ROOT.iterdir()):
        if session_dir.is_dir() and session_dir.name.startswith("10AE"):
            paths.extend(_hierarchy_paths(session_dir))
    return paths


@pytest.mark.skipif(
    not (_CAPTURES_ROOT / "10AE7S00HD002JK_2026-05-28_231945").is_dir(),
    reason="fixture missing",
)
def test_stale_session_tap_pid_corrected_to_on_screen_post() -> None:
    """Production may pass pre-tap pid while UI already shows another post."""
    path = (
        _CAPTURES_ROOT
        / "10AE7S00HD002JK_2026-05-28_231945"
        / "step_000_tap_fb_comment_button_hierarchy.xml"
    )
    xml = path.read_text(encoding="utf-8")
    stale_pid = "60b6bd6d66f3e1e2"  # Thái Hoàng from pre-capture tap target
    rows, diag = parse_fb_comments_from_xml_with_diagnostic(xml, stale_pid)
    bodies = [r for r in rows if r.get("_type") != "post_stats"]
    assert diag["reason_code"] == "ok"
    assert len(bodies) == 1
    assert bodies[0]["parent_post_id"] == "ee5add7e48beb17f"
    assert "Hoàng" in str(bodies[0].get("author") or "")


@pytest.mark.skipif(not _CAPTURES_ROOT.is_dir(), reason="local capture fixtures missing")
def test_all_captures_comment_post_mapping_pass() -> None:
    results = verify_all_captures(_CAPTURES_ROOT)
    summary = summarize_results(results)
    assert summary["fail"] == 0, summary["failed"]


@pytest.mark.skipif(not _CAPTURES_ROOT.is_dir(), reason="local capture fixtures missing")
@pytest.mark.parametrize(
    "capture_path",
    _all_capture_paths(),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_capture_file_comment_post_mapping(capture_path: Path) -> None:
    session_dir = capture_path.parent
    tap_pid, _ = resolve_session_tap_parent_pid(session_dir)
    result = verify_capture_file(capture_path, _CAPTURES_ROOT, tap_pid)
    assert result.status != "fail", (
        f"{result.rel_path}: {result.issues} "
        f"(expected_pid={result.expected_pid}, source={result.expected_source})"
    )
