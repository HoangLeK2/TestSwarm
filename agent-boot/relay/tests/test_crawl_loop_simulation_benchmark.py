"""
End-to-end crawl loop simulation: XML dump, tap, scroll, parse — with latency stats.

Run:
  cd agent-boot && uv run pytest relay/tests/test_crawl_loop_simulation_benchmark.py -v -s
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from relay.extra_data.collector import (
    collect_fb_comment_filter_apply,
    collect_fb_comment_target_with_tap,
    collect_xml_snapshots,
)
from relay.extra_data.ingest import _parse_items
from relay.tests.test_comment_filter import _sheet_xml
from relay.tests.test_extra_data_collector import _FakeExecutor, _SessionFakeExecutor
from relay.tests.test_post_open_resolver import _feed_card_xml

# Simulated u2/ADB latency per op (ms) — keeps tests fast but measurable.
_SIM_DUMP_MS = 3.0
_SIM_SWIPE_MS = 0.8
_SIM_CLICK_MS = 1.5
_SIM_KEY_MS = 0.4

CRAWL_WINDOW_HOURS = 18
SECONDS_PER_CRAWL_WINDOW = CRAWL_WINDOW_HOURS * 60 * 60
TARGET_CRAWL_WINDOW_CONTENT_ITEMS = 50_000

# Production crawl profile (balanced) — pause zeroed for deterministic bench.
CRAWL_FB_COMMENTS_CONTEXT: dict[str, Any] = {
    "comment_scroll_passes": 48,
    "comment_swipes_per_dump": 3,
    "comment_scroll_distance": 0.30,
    "comment_scroll_duration_ms": 300,
    "comment_scroll_pause_s": 0,
    "comment_no_growth_break": 3,
    "min_comment_scan_passes": 2,
    "comment_recover_chrome": False,
    "stop_if_no_new": False,
    "no_new_threshold": 4,
    "parent_post_id": "pid-test-001",
    "persist": False,
    "return_items": True,
}

LEGACY_BALANCED_FB_COMMENTS_CONTEXT: dict[str, Any] = {
    "expand_see_more": False,
    "hierarchy_compressed": True,
    "hierarchy_dump_timeout_s": 2.2,
    "max_items": 400,
    "comment_scroll_passes": 40,
    "comment_swipes_per_dump": 6,
    "comment_scroll_distance": 0.52,
    "comment_scroll_duration_ms": 120,
    "comment_scroll_pause_s": 0.0,
    "comment_recover_chrome": False,
    "comment_no_growth_break": 2,
    "min_comment_scan_passes": 1,
    "comment_max_snapshots": 28,
    "comment_stop_if_no_new": False,
    "stop_if_no_new": False,
    "no_new_threshold": 3,
    "parent_post_id": "pid-test-001",
    "persist": False,
    "return_items": True,
}

CRAWL_FB_POSTS_CONTEXT: dict[str, Any] = {
    "expand_see_more": False,
    "open_post_before_extract": False,
    "persist": False,
    "return_items": True,
}

CRAWL_TAP_CONTEXT: dict[str, Any] = {
    "post_tap_wait_s": 0,
    "comment_target_verify": True,
    "comment_target_verify_max_retries": 1,
    "comment_target_verify_back_settle_s": 0,
    "comment_sheet_u2_wait": 0,
    "comment_sheet_wait_s": 0,
    "comment_target_tap_enabled": True,
}


@dataclass
class OpStats:
    dump: int = 0
    swipe: int = 0
    click: int = 0
    click_spec: int = 0
    click_selector: int = 0
    press_key: int = 0
    wait_exists: int = 0
    total_ops: int = 0
    total_sim_ms: float = 0.0
    total_device_ms: float = 0.0
    wall_ms: float = 0.0
    _sim_by_op: dict[str, float] = field(default_factory=dict)
    _device_by_op: dict[str, float] = field(default_factory=dict)

    def record(self, op: str, sim_ms: float, device_ms: float | None = None) -> None:
        if device_ms is None:
            device_ms = sim_ms
        self.total_ops += 1
        self.total_sim_ms += sim_ms
        self.total_device_ms += device_ms
        self._sim_by_op[op] = self._sim_by_op.get(op, 0.0) + sim_ms
        self._device_by_op[op] = self._device_by_op.get(op, 0.0) + device_ms
        if op == "dump_hierarchy":
            self.dump += 1
        elif op == "swipe":
            self.swipe += 1
        elif op == "click":
            self.click += 1
        elif op == "click_spec":
            self.click_spec += 1
        elif op == "click_selector":
            self.click_selector += 1
        elif op == "press_key":
            self.press_key += 1
        elif op == "wait_exists":
            self.wait_exists += 1

    def summary(self) -> dict[str, Any]:
        avg_op = self.total_sim_ms / self.total_ops if self.total_ops else 0.0
        click_total = self.click + self.click_spec + self.click_selector
        click_sim = (
            self._sim_by_op.get("click", 0)
            + self._sim_by_op.get("click_spec", 0)
            + self._sim_by_op.get("click_selector", 0)
        )
        dump_sim = self._sim_by_op.get("dump_hierarchy", 0.0)
        swipe_sim = self._sim_by_op.get("swipe", 0.0)
        return {
            "wall_ms": round(self.wall_ms, 2),
            "total_ops": self.total_ops,
            "dump": self.dump,
            "swipe": self.swipe,
            "click": click_total,
            "press_key": self.press_key,
            "sim_total_ms": round(self.total_sim_ms, 2),
            "device_total_ms": round(self.total_device_ms, 2),
            "avg_sim_ms_per_op": round(avg_op, 3),
            "avg_sim_ms_per_dump": round(dump_sim / self.dump, 3) if self.dump else 0,
            "avg_sim_ms_per_swipe": round(swipe_sim / self.swipe, 3) if self.swipe else 0,
            "avg_sim_ms_per_click": round(click_sim / click_total, 3) if click_total else 0,
        }


class _InstrumentedExecutor(_FakeExecutor):
    """Fake u2 executor with per-op simulated latency + stats."""

    def __init__(
        self,
        xml: str,
        *,
        stats: OpStats,
        sheet_after_click: str | None = None,
        window: tuple[int, int] = (1080, 2340),
    ) -> None:
        super().__init__(xml=xml, window=window)
        self.stats = stats
        self._sheet_after_click = sheet_after_click or _sheet_xml()
        self._opened_sheet = False

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        t0 = time.perf_counter()
        for act in actions:
            op = act.get("op", "")
            sim = {
                "dump_hierarchy": _SIM_DUMP_MS,
                "swipe": _SIM_SWIPE_MS,
                "click": _SIM_CLICK_MS,
                "click_spec": _SIM_CLICK_MS,
                "click_selector": _SIM_CLICK_MS,
                "press_key": _SIM_KEY_MS,
                "wait_exists": 0.2,
            }.get(op, 0.1)
            device_ms = sim
            if op == "swipe":
                device_ms = max(sim, float(act.get("duration") or 0) * 1000.0)
            elif op == "sleep":
                device_ms = max(sim, float(act.get("seconds", act.get("duration", 0)) or 0) * 1000.0)
            self.stats.record(op, sim, device_ms)
            if sim > 0:
                await asyncio.sleep(sim / 1000.0)
            if op in {"click", "click_spec", "click_selector"} and not self._opened_sheet:
                self._dump_xml = self._sheet_after_click
                self._opened_sheet = True
        result = await super().run_batch(serial, actions, early_exit=early_exit)
        self.stats.wall_ms += (time.perf_counter() - t0) * 1000
        return result


class _InstrumentedSessionExecutor(_SessionFakeExecutor):
    """Session-scoped executor for comment target tap with instrumentation."""

    def __init__(
        self,
        xml: str,
        *,
        stats: OpStats,
        sheet_after_click: str | None = None,
    ) -> None:
        super().__init__(xml=xml)
        self.stats = stats
        self._sheet_after_click = sheet_after_click or _sheet_xml()
        self._opened_sheet = False

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        t0 = time.perf_counter()
        for act in actions:
            op = act.get("op", "")
            sim = {
                "dump_hierarchy": _SIM_DUMP_MS,
                "swipe": _SIM_SWIPE_MS,
                "click": _SIM_CLICK_MS,
                "click_spec": _SIM_CLICK_MS,
                "click_selector": _SIM_CLICK_MS,
                "press_key": _SIM_KEY_MS,
                "wait_exists": 0.2,
            }.get(op, 0.1)
            device_ms = sim
            if op == "swipe":
                device_ms = max(sim, float(act.get("duration") or 0) * 1000.0)
            elif op == "sleep":
                device_ms = max(sim, float(act.get("seconds", act.get("duration", 0)) or 0) * 1000.0)
            self.stats.record(op, sim, device_ms)
            if sim > 0:
                await asyncio.sleep(sim / 1000.0)
            if op in {"click", "click_spec", "click_selector"} and not self._opened_sheet:
                self._dump_xml = self._sheet_after_click
                self._opened_sheet = True
        result = await _FakeExecutor.run_batch(self, serial, actions, early_exit=early_exit)
        self.stats.wall_ms += (time.perf_counter() - t0) * 1000
        return result


class _GrowingCommentExecutor(_InstrumentedExecutor):
    """Keep the comment sheet structurally valid while making each dump unique."""

    def __init__(self, *, stats: OpStats) -> None:
        super().__init__(_sheet_xml(), stats=stats)
        self._dump_n = 0

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        if actions and any(act.get("op") == "dump_hierarchy" for act in actions):
            self._dump_n += 1
            self._dump_xml = _sheet_xml().replace(
                'rotation="0"',
                f'rotation="{self._dump_n}"',
            )
        return await super().run_batch(serial, actions, early_exit=early_exit)


def _load_crawl_group_comment_context() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    path = root / "Crawl group (2).json"
    if not path.is_file():
        return dict(CRAWL_FB_COMMENTS_CONTEXT)
    data = json.loads(path.read_text(encoding="utf-8"))
    loop = next(
        (s for s in data["scenario"]["body"]["steps"] if s.get("type") == "loop"),
        None,
    )
    if not loop:
        return dict(CRAWL_FB_COMMENTS_CONTEXT)
    tap = next(
        (s for s in loop.get("steps", []) if s.get("type") == "fb_tap_comment_button"),
        None,
    )
    if not tap:
        return dict(CRAWL_FB_COMMENTS_CONTEXT)
    extract = next(
        (
            s
            for s in tap.get("then", [])
            if s.get("type") == "extract" and s.get("strategy") == "fb_comments"
        ),
        None,
    )
    if not extract:
        return dict(CRAWL_FB_COMMENTS_CONTEXT)
    ctx = dict(CRAWL_FB_COMMENTS_CONTEXT)
    for key in (
        "comment_scroll_passes",
        "comment_swipes_per_dump",
        "comment_scroll_distance",
        "comment_scroll_duration_ms",
        "comment_scroll_pause_s",
        "comment_no_growth_break",
        "min_comment_scan_passes",
        "stop_if_no_new",
        "no_new_threshold",
        "max_items",
    ):
        if key in extract:
            ctx[key] = extract[key]
    ctx["comment_scroll_pause_s"] = 0
    ctx["comment_recover_chrome"] = False
    return ctx


def _current_balanced_comment_context() -> dict[str, Any]:
    try:
        from services.extract_profiles import get_profile_defaults
    except ModuleNotFoundError:
        import sys

        repo_root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(repo_root / "device_farm"))
        from services.extract_profiles import get_profile_defaults

    ctx = dict(get_profile_defaults("balanced", "fb_comments"))
    ctx["comment_recover_chrome"] = False
    ctx["parent_post_id"] = "pid-test-001"
    ctx["persist"] = False
    ctx["return_items"] = True
    return ctx


def _estimate_comment_device_ms(stats: OpStats, context: dict[str, Any], snapshots: int) -> float:
    parse_ms_per_snapshot = 80.0
    return stats.total_device_ms + snapshots * parse_ms_per_snapshot


def _crawl_window_content_items(total_items: int, seconds_per_detail: float) -> float:
    if seconds_per_detail <= 0:
        return 0.0
    return total_items * SECONDS_PER_CRAWL_WINDOW / seconds_per_detail


def _required_items_per_detail(seconds_per_detail: float) -> float:
    return TARGET_CRAWL_WINDOW_CONTENT_ITEMS * seconds_per_detail / SECONDS_PER_CRAWL_WINDOW


def _crawl_window_content_items_for_mixed_distribution(
    *,
    commented_post_ratio: float,
    avg_comments_per_commented_post: float,
    seconds_per_post_scan: float,
    seconds_per_commented_detail: float,
) -> dict[str, float]:
    ratio = max(0.0, min(1.0, commented_post_ratio))
    seconds_per_seen_post = seconds_per_post_scan + ratio * seconds_per_commented_detail
    items_per_seen_post = 1.0 + ratio * avg_comments_per_commented_post
    window_posts_seen = (
        SECONDS_PER_CRAWL_WINDOW / seconds_per_seen_post
        if seconds_per_seen_post > 0
        else 0.0
    )
    window_items = window_posts_seen * items_per_seen_post
    target_items_per_second = TARGET_CRAWL_WINDOW_CONTENT_ITEMS / SECONDS_PER_CRAWL_WINDOW
    if ratio <= 0:
        required_comments = float("inf")
    else:
        required_comments = (
            target_items_per_second * seconds_per_seen_post - 1.0
        ) / ratio
    return {
        "avg_comments_per_commented_post": avg_comments_per_commented_post,
        "commented_post_ratio": ratio,
        "estimated_window_items": window_items,
        "items_per_seen_post": items_per_seen_post,
        "required_comments_per_commented_post": max(0.0, required_comments),
        "seconds_per_seen_post": seconds_per_seen_post,
        "window_posts_seen": window_posts_seen,
    }


async def _simulate_long_comment_thread(context: dict[str, Any]) -> dict[str, Any]:
    stats = OpStats()
    exec_ = _GrowingCommentExecutor(stats=stats)
    t0 = time.perf_counter()
    snapshots, err = await collect_xml_snapshots(exec_, "bench-dev", "fb_comments", dict(context))
    wall_ms = (time.perf_counter() - t0) * 1000
    assert err is None
    summary = stats.summary()
    estimated_ms = _estimate_comment_device_ms(stats, context, len(snapshots))
    return {
        "snapshots": len(snapshots),
        "dump": summary["dump"],
        "swipe": summary["swipe"],
        "sim_wall_ms": round(wall_ms, 2),
        "estimated_device_s": round(estimated_ms / 1000.0, 2),
        "context": {
            "max_items": context.get("max_items"),
            "comment_scroll_passes": context.get("comment_scroll_passes"),
            "comment_swipes_per_dump": context.get("comment_swipes_per_dump"),
            "comment_max_snapshots": context.get("comment_max_snapshots"),
            "comment_scroll_wall_s": context.get("comment_scroll_wall_s"),
            "comment_stop_if_no_new": context.get("comment_stop_if_no_new"),
        },
    }


async def _simulate_crawl_iteration(
    *,
    comment_context: dict[str, Any] | None = None,
    apply_filter: bool = False,
) -> tuple[OpStats, dict[str, Any]]:
    stats = OpStats()
    feed_xml = _feed_card_xml(
        author="Bench User",
        metadata="2 giờ",
        body="Post body for crawl benchmark simulation",
    )
    sheet_xml = _sheet_xml(current_filter="most_relevant")
    exec_ = _InstrumentedExecutor(feed_xml, stats=stats, sheet_after_click=sheet_xml)
    exec_session = _InstrumentedSessionExecutor(
        feed_xml, stats=stats, sheet_after_click=sheet_xml
    )

    report: dict[str, Any] = {"phases": {}}

    t0 = time.perf_counter()
    post_snaps, post_err = await collect_xml_snapshots(
        exec_, "bench-dev", "fb_posts", CRAWL_FB_POSTS_CONTEXT
    )
    post_items, _ = _parse_items("fb_posts", post_snaps[0], {}) if post_snaps else ([], {})
    report["phases"]["fb_posts"] = {
        "err": post_err,
        "snapshots": len(post_snaps),
        "parsed": len(post_items),
        "ms": round((time.perf_counter() - t0) * 1000, 2),
    }

    t0 = time.perf_counter()
    _tap_snaps, tap_err, tapped, tap_diag = await collect_fb_comment_target_with_tap(
        exec_session,
        "bench-dev",
        dict(CRAWL_TAP_CONTEXT),
    )
    report["phases"]["fb_comment_target_tap"] = {
        "err": tap_err,
        "tapped": tapped,
        "verified": tap_diag.get("verified"),
        "reason": tap_diag.get("reason_code"),
        "ms": round((time.perf_counter() - t0) * 1000, 2),
    }

    if apply_filter:
        t0 = time.perf_counter()
        exec_._dump_xml = sheet_xml
        filter_report, filter_err = await collect_fb_comment_filter_apply(
            exec_,
            "bench-dev",
            {"comment_filter": "all_comments", "comment_filter_settle_s": 0},
        )
        report["phases"]["fb_comment_filter"] = {
            "err": filter_err,
            "switched": (filter_report or {}).get("switched"),
            "ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    ctx = dict(comment_context or _load_crawl_group_comment_context())
    exec_._dump_xml = sheet_xml
    t0 = time.perf_counter()
    comment_snaps, comment_err = await collect_xml_snapshots(
        exec_, "bench-dev", "fb_comments", ctx
    )
    parse_t0 = time.perf_counter()
    all_items: list[dict[str, Any]] = []
    for snap in comment_snaps:
        items, _ = _parse_items("fb_comments", snap, ctx)
        all_items.extend(items)
    parse_ms = (time.perf_counter() - parse_t0) * 1000
    collect_ms = (time.perf_counter() - t0) * 1000 - parse_ms
    report["phases"]["fb_comments"] = {
        "err": comment_err,
        "snapshots": len(comment_snaps),
        "unique_parsed": len(all_items),
        "collect_ms": round(collect_ms, 2),
        "parse_ms": round(parse_ms, 2),
    }

    report["stats"] = stats.summary()
    report["stats"]["parse_ms"] = round(parse_ms, 2)
    return stats, report


@pytest.mark.asyncio
async def test_crawl_iteration_simulates_dump_tap_scroll_counts() -> None:
    stats, report = await _simulate_crawl_iteration(apply_filter=True)
    s = stats.summary()
    assert report["phases"]["fb_posts"]["err"] is None
    assert report["phases"]["fb_comment_target_tap"]["tapped"] is True
    assert report["phases"]["fb_comments"]["err"] is None
    assert s["dump"] >= 3, f"expected multiple dumps, got {s}"
    assert s["swipe"] >= 1, f"expected scroll swipes, got {s}"
    assert s["click"] >= 1, f"expected at least one tap, got {s}"
    assert report["phases"]["fb_comment_filter"]["err"] is None


@pytest.mark.asyncio
async def test_crawl_iteration_benchmark_average_latency() -> None:
    n = 5
    wall_samples: list[float] = []
    dump_samples: list[float] = []
    swipe_samples: list[float] = []
    reports: list[dict[str, Any]] = []

    for _ in range(n):
        stats, report = await _simulate_crawl_iteration()
        reports.append(report)
        s = stats.summary()
        wall_samples.append(s["wall_ms"])
        if s["dump"]:
            dump_samples.append(s["avg_sim_ms_per_dump"])
        if s["swipe"]:
            swipe_samples.append(s["avg_sim_ms_per_swipe"])

    avg_wall = statistics.mean(wall_samples)
    p95_wall = sorted(wall_samples)[max(0, int(n * 0.95) - 1)]
    avg_dump = statistics.mean(dump_samples) if dump_samples else 0
    avg_swipe = statistics.mean(swipe_samples) if swipe_samples else 0

    assert avg_wall < 800, f"avg wall {avg_wall}ms too slow"
    assert p95_wall < 1200, f"p95 wall {p95_wall}ms too slow"
    assert avg_dump <= _SIM_DUMP_MS * 1.5 + 1, f"avg dump op {avg_dump}ms"
    assert avg_swipe <= _SIM_SWIPE_MS * 1.5 + 1, f"avg swipe op {avg_swipe}ms"

    print(
        f"\n[crawl-bench] iterations={n} "
        f"avg_wall={avg_wall:.1f}ms p95_wall={p95_wall:.1f}ms "
        f"avg_dump_op={avg_dump:.2f}ms avg_swipe_op={avg_swipe:.2f}ms "
        f"last={reports[-1]['stats']}"
    )


@pytest.mark.asyncio
async def test_crawl_comments_deep_scroll_profile_matches_production() -> None:
    ctx = _load_crawl_group_comment_context()
    assert ctx["comment_scroll_passes"] == 48
    assert ctx["comment_swipes_per_dump"] == 3
    stats = OpStats()
    exec_ = _InstrumentedExecutor(_sheet_xml(), stats=stats)
    snapshots, err = await collect_xml_snapshots(exec_, "dev1", "fb_comments", ctx)
    assert err is None
    assert snapshots
    s = stats.summary()
    # After the first unchanged dump, adaptive stall detection checks the tail
    # with 2-swipe batches instead of repeating full 3-swipe batches.
    assert s["swipe"] == 7
    assert s["dump"] == 4
    assert s["wall_ms"] < 500


@pytest.mark.asyncio
async def test_crawl_comments_default_fast_timing_keeps_requested_budget() -> None:
    legacy = await _simulate_long_comment_thread(LEGACY_BALANCED_FB_COMMENTS_CONTEXT)
    current = await _simulate_long_comment_thread(_current_balanced_comment_context())

    reduction = {
        "swipe_pct": round((1 - current["swipe"] / legacy["swipe"]) * 100, 1),
        "dump_pct": round((1 - current["dump"] / legacy["dump"]) * 100, 1),
        "estimated_device_pct": round(
            (1 - current["estimated_device_s"] / legacy["estimated_device_s"]) * 100,
            1,
        ),
    }
    print(
        "\n[crawl-bench-balanced] "
        f"legacy={legacy} current={current} reduction={reduction}"
    )

    assert legacy["swipe"] == 40
    assert legacy["dump"] == 8
    assert legacy["sim_wall_ms"] < 300
    assert current["swipe"] <= 16
    assert current["dump"] < legacy["dump"]
    assert reduction["estimated_device_pct"] >= 40


@pytest.mark.asyncio
async def test_crawl_18h_content_throughput_reaches_50k_with_comment_yield() -> None:
    current = await _simulate_long_comment_thread(_current_balanced_comment_context())
    current_seconds = float(current["estimated_device_s"])
    current_items_per_detail = 51  # 1 post + 50 comments.
    current_window_items = _crawl_window_content_items(current_items_per_detail, current_seconds)

    # Calibration row from an older live observation: fb_posts ~= 5.9s,
    # fb_comments ~= 41.8s. This keeps the benchmark honest when synthetic
    # op timings are much faster than a real phone/app session.
    live_like_seconds = 47.7
    live_like_items_per_detail = 51
    live_like_window_items = _crawl_window_content_items(
        live_like_items_per_detail,
        live_like_seconds,
    )
    live_like_required_items = _required_items_per_detail(live_like_seconds)

    report = {
        "crawl_window_hours": CRAWL_WINDOW_HOURS,
        "target_window_items": TARGET_CRAWL_WINDOW_CONTENT_ITEMS,
        "target_items_per_second": round(
            TARGET_CRAWL_WINDOW_CONTENT_ITEMS / SECONDS_PER_CRAWL_WINDOW,
            3,
        ),
        "current_synthetic": {
            "seconds_per_detail": current_seconds,
            "items_per_detail": current_items_per_detail,
            "estimated_window_items": round(current_window_items),
            "required_items_per_detail": round(_required_items_per_detail(current_seconds), 2),
            "profile": current,
        },
        "live_like_older_observation": {
            "seconds_per_detail": live_like_seconds,
            "items_per_detail": live_like_items_per_detail,
            "estimated_window_items": round(live_like_window_items),
            "required_items_per_detail": round(live_like_required_items, 2),
        },
    }
    print(f"\n[crawl-bench-50k-18h] {json.dumps(report, ensure_ascii=False, sort_keys=True)}")

    assert current_window_items >= TARGET_CRAWL_WINDOW_CONTENT_ITEMS
    assert live_like_window_items >= TARGET_CRAWL_WINDOW_CONTENT_ITEMS
    assert live_like_required_items <= live_like_items_per_detail


def test_crawl_18h_mixed_comment_distribution_identifies_sparse_risk() -> None:
    # Older live-like split: scanning/parsing a post ~= 5.9s; opening and
    # crawling comments adds ~= 41.8s. Posts with zero comments should be
    # counted as post items but should not pay the detail crawl cost.
    seconds_per_post_scan = 5.9
    seconds_per_commented_detail = 41.8
    profiles = {
        "dense_40pct_50_comments": _crawl_window_content_items_for_mixed_distribution(
            commented_post_ratio=0.40,
            avg_comments_per_commented_post=50,
            seconds_per_post_scan=seconds_per_post_scan,
            seconds_per_commented_detail=seconds_per_commented_detail,
        ),
        "sparse_10pct_50_comments": _crawl_window_content_items_for_mixed_distribution(
            commented_post_ratio=0.10,
            avg_comments_per_commented_post=50,
            seconds_per_post_scan=seconds_per_post_scan,
            seconds_per_commented_detail=seconds_per_commented_detail,
        ),
        "sparse_10pct_110_comments": _crawl_window_content_items_for_mixed_distribution(
            commented_post_ratio=0.10,
            avg_comments_per_commented_post=110,
            seconds_per_post_scan=seconds_per_post_scan,
            seconds_per_commented_detail=seconds_per_commented_detail,
        ),
    }
    report = {
        "crawl_window_hours": CRAWL_WINDOW_HOURS,
        "target_window_items": TARGET_CRAWL_WINDOW_CONTENT_ITEMS,
        "target_items_per_second": round(
            TARGET_CRAWL_WINDOW_CONTENT_ITEMS / SECONDS_PER_CRAWL_WINDOW,
            3,
        ),
        "assumptions": {
            "seconds_per_post_scan": seconds_per_post_scan,
            "seconds_per_commented_detail": seconds_per_commented_detail,
        },
        "profiles": {
            name: {
                key: round(value, 2)
                for key, value in profile.items()
            }
            for name, profile in profiles.items()
        },
    }
    print(
        "\n[crawl-bench-50k-18h-mixed] "
        f"{json.dumps(report, ensure_ascii=False, sort_keys=True)}"
    )

    assert (
        profiles["dense_40pct_50_comments"]["estimated_window_items"]
        >= TARGET_CRAWL_WINDOW_CONTENT_ITEMS
    )
    assert (
        profiles["sparse_10pct_50_comments"]["estimated_window_items"]
        < TARGET_CRAWL_WINDOW_CONTENT_ITEMS
    )
    assert (
        profiles["sparse_10pct_110_comments"]["estimated_window_items"]
        >= TARGET_CRAWL_WINDOW_CONTENT_ITEMS
    )


@pytest.mark.asyncio
async def test_crawl_xml_parse_throughput() -> None:
    xml = _sheet_xml()
    iterations = 200
    t0 = time.perf_counter()
    total_items = 0
    for _ in range(iterations):
        items, diag = _parse_items("fb_comments", xml, {"parent_post_id": "p1"})
        total_items += len(items)
        assert diag.get("reason_code") in {
            None,
            "ok",
            "empty",
            "no_items",
            "no_nodes_in_band",
        }
    elapsed_ms = (time.perf_counter() - t0) * 1000
    per_parse_us = (elapsed_ms * 1000) / iterations
    print(f"\n[crawl-bench] xml_parse {iterations}x avg={per_parse_us:.1f}µs/op items={total_items}")
    assert per_parse_us < 5000, f"parse too slow: {per_parse_us}µs/op"
