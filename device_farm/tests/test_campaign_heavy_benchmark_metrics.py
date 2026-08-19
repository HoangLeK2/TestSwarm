"""Contract tests for the heavy campaign benchmark metrics."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_benchmark_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_campaign_100_heavy.py"
    spec = importlib.util.spec_from_file_location("benchmark_campaign_100_heavy", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_phase_for_step_groups_crawl_and_u2_paths():
    bench = _load_benchmark_module()

    assert bench._phase_for_step("extract", "extract:fb_comments") == "crawl_comments"
    assert bench._phase_for_step("extract", "extract:fb_posts") == "crawl_posts"
    assert bench._phase_for_step("u2", "tap_selector") == "u2_interaction"
    assert bench._phase_for_step("u2", "scroll_to") == "u2_navigation"


def test_comment_fast_scroll_profile_marks_nested_fb_comment_extracts():
    bench = _load_benchmark_module()
    steps = [
        {
            "type": "loop",
            "steps": [
                {"type": "extract", "entity": "posts", "platform": "facebook"},
                {"type": "extract", "entity": "comments", "platform": "facebook"},
            ],
        }
    ]

    bench._apply_comment_fast_scroll_profile(
        steps,
        swipes_per_dump=12,
        distance=0.68,
        duration_ms=80,
    )

    fb_posts, fb_comments = steps[0]["steps"]
    assert "comment_large_target_fast_scroll" not in fb_posts
    assert fb_comments["comment_large_target_fast_scroll"] is True
    assert fb_comments["comment_large_target_swipes_per_dump"] == 12
    assert fb_comments["comment_large_target_scroll_distance"] == 0.68
    assert fb_comments["comment_large_target_duration_ms"] == 80


def test_summary_exposes_critical_path_resource_pressure_and_tail_phones():
    bench = _load_benchmark_module()
    resources = {
        "u2": bench._Resource("u2", 2),
        "extract": bench._Resource("extract", 1),
        "cpu": bench._Resource("cpu", 1),
    }
    resources["u2"].wait_ms.extend([0.0, 1.0, 5.0])
    resources["u2"].active_samples.extend([1, 2, 2])
    resources["u2"].max_active = 2
    samples = [
        {
            "serial": "bench-1",
            "ok": True,
            "elapsed_ms": 10.0,
            "virtual_ms": 100.0,
            "resources": {"u2": 30.0, "extract": 70.0},
            "resource_wait_ms": {"u2": 1.0},
            "phases": {"u2_interaction": 30.0, "crawl_comments": 70.0},
            "phase_wait_ms": {"u2_interaction": 1.0},
            "steps": {"tap_selector": 1, "extract:fb_comments": 1},
            "errors": [],
        },
        {
            "serial": "bench-2",
            "ok": True,
            "elapsed_ms": 20.0,
            "virtual_ms": 130.0,
            "resources": {"u2": 40.0, "extract": 90.0},
            "resource_wait_ms": {"extract": 2.0},
            "phases": {"u2_navigation": 40.0, "crawl_comments": 90.0},
            "phase_wait_ms": {"crawl_comments": 2.0},
            "steps": {"scroll_to": 1, "extract:fb_comments": 1},
            "errors": [],
        },
    ]

    summary = bench._summarize(samples, resources)

    assert summary["critical_path_virtual_ms_total"]["crawl_comments"] == 160.0
    assert summary["critical_path_wait_ms_total"]["crawl_comments"] == 2.0
    assert summary["resource_pressure"]["u2"]["max_active"] == 2
    assert summary["tail_phones"][0]["serial"] == "bench-2"
    assert summary["tail_phones"][0]["top_phases"][0] == ("crawl_comments", 90.0)
