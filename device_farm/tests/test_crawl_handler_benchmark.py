"""Benchmark device_farm step handlers for crawl comment flow (mocked device)."""
from __future__ import annotations

import statistics
import time
from types import SimpleNamespace
from typing import Any

import pytest

from tasks.scenario.steps import control_flow
from tasks.scenario.steps import extraction as extraction_mod


class _BenchDevice:
    serial = "bench-serial"

    def __init__(self) -> None:
        self.swipes: list[tuple[Any, ...]] = []
        self.calls: list[dict[str, Any]] = []

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    def request_extra_data_xml(self, **kwargs):
        self.calls.append(kwargs)
        strategy = kwargs.get("strategy", "")
        entity = kwargs.get("entity", "")
        if strategy in {"fb_comment_target", "fb_comment_target_tap"}:
            return {
                "ok": True,
                "ingest": {
                    "diagnostic": {
                        "reason_code": "ok",
                        "target": {
                            "bounds": [360, 1800, 520, 1860],
                            "post_key": "pk-bench",
                            "_pid": "pid-bench",
                        },
                        "candidate_count": 1,
                    }
                },
                "agent_tapped": True,
            }
        if entity == "comments":
            return {
                "ok": True,
                "ingest": {
                    "parsed_count": 12,
                    "inserted_count": 10,
                    "duplicate_count": 2,
                    "diagnostic": {"reason_code": "ok"},
                    "items": [{"comment_key": f"c{i}", "text": f"comment {i}"} for i in range(12)],
                },
                "route": "relay_u2",
            }
        return {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
                "items": [{"post_key": "p1", "text": "post"}],
            },
            "route": "relay_u2",
        }


def _ctx(device: _BenchDevice) -> SimpleNamespace:
    return SimpleNamespace(
        serial=device.serial,
        device=device,
        w=1080,
        h=2340,
        ctx={
            "_active_comment_parent_source": "post_detail",
            "_active_comment_parent_hash": "hash-bench",
            "_comment_parent_pid": "pid-bench",
            "_active_comment_anchor_verified": True,
        },
        scenario={
            "platform": "facebook",
            "_execution_id": "exec",
            "_campaign_id": "camp",
            "_campaign_vars": {"__USER_ID__": "user"},
            "name": "bench",
        },
        cancel_event=None,
    )


@pytest.fixture(autouse=True)
def _relay_available(monkeypatch):
    monkeypatch.setattr(extraction_mod, "_relay_extra_data_available", lambda _device: True)
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setenv("EDGE_EXTRA_RELAY_ENABLED", "1")


def test_social_open_comments_handler_benchmark(monkeypatch) -> None:
    monkeypatch.setattr(
        "tasks.scenario.steps.extraction.run_edge_comment_filter_switch",
        lambda **_: {"switched": False, "reason_code": "already_all_comments"},
    )
    monkeypatch.setattr(
        "tasks.scenario.steps.extraction._resolve_campaign_id_for_edge",
        lambda *_: "camp-bench",
    )
    monkeypatch.setattr(
        "tasks.scenario.steps.extraction.request_edge_comment_target",
        lambda **_: {
            "bounds": [360, 1800, 520, 1860],
            "post_key": "pk-bench",
            "_pid": "pid-bench",
            "_agent_tapped": True,
        },
    )
    monkeypatch.setattr(control_flow.time, "sleep", lambda _s: None)
    device = _BenchDevice()
    sc = _ctx(device)
    sc.ctx.pop("_active_comment_parent_hash", None)
    sc.ctx.pop("_comment_parent_pid", None)
    sc.ctx.pop("_active_comment_anchor_verified", None)
    step = {
        "type": "social_open_comments",
        "pre_scroll": True,
        "pre_scroll_distance": 0.24,
        "post_tap_wait_s": 0,
        "pre_scroll_pause_s": 0,
        "switch_to_all_comments": False,
        "then": [{"type": "extract", "entity": "comments", "platform": "facebook"}],
        "else": [],
    }
    samples: list[float] = []
    for _ in range(20):
        result: dict[str, Any] = {}
        t0 = time.perf_counter()
        control_flow.handle_social_open_comments(sc, step, 0, result)
        samples.append((time.perf_counter() - t0) * 1000)
        assert result.get("ok") is not False

    avg = statistics.mean(samples)
    p95 = sorted(samples)[18]
    assert len(device.swipes) >= 20
    assert avg < 5, f"handler avg {avg}ms too slow (mocked relay/sleep)"
    print(
        f"\n[handler-bench] social_open_comments 20x avg={avg:.2f}ms p95={p95:.2f}ms "
        f"swipes={len(device.swipes)}"
    )


def test_fb_comments_extract_handler_benchmark(monkeypatch) -> None:
    monkeypatch.setattr(
        "tasks.scenario.steps.extraction._resolve_campaign_id_for_edge",
        lambda *_: "camp-bench",
    )
    monkeypatch.setattr(
        extraction_mod,
        "resolve_step_comment_filter",
        lambda _step: None,
    )
    device = _BenchDevice()
    sc = _ctx(device)
    sc.ctx["_comment_filter_applied"] = "all_comments"
    step = {
        "type": "extract",
        "entity": "comments", "platform": "facebook",
        "edge_extra_data": True,
        "max_items": 500,
        "comment_scroll_passes": 48,
        "comment_swipes_per_dump": 3,
        "collection": "bench",
        "dedupe_field": "comment_key",
    }
    samples: list[float] = []
    for _ in range(20):
        result: dict[str, Any] = {}
        t0 = time.perf_counter()
        handled = extraction_mod._try_edge_extra_data(sc, step, "comments", "facebook", result)
        samples.append((time.perf_counter() - t0) * 1000)
        assert handled is True
        assert result.get("extracted") == 10

    avg = statistics.mean(samples)
    p95 = sorted(samples)[18]
    comment_calls = [c for c in device.calls if c.get("entity") == "comments"]
    assert len(comment_calls) == 20
    assert avg < 30, f"extract handler avg {avg}ms too slow"
    print(
        f"\n[handler-bench] comments extract 20x avg={avg:.2f}ms p95={p95:.2f}ms "
        f"relay_calls={len(comment_calls)}"
    )
