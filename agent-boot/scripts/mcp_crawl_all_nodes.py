#!/usr/bin/env python3
"""
Chạy TẤT CẢ loại node trong scenario crawl group qua Device Farm MCP — không chỉ df_hierarchy.

Mỗi step type được map tới MCP tool trực tiếp (df_key, df_scroll, df_swipe, …) hoặc
df_run_scenario cho node composite (extract, fb_tap_comment_button, if_element, loop).

Usage:
  cd agent-boot
  uv run python scripts/mcp_crawl_all_nodes.py --mode catalog
  uv run python scripts/mcp_crawl_all_nodes.py --mode observe --serial 10AE7S00HD002JK
  uv run python scripts/mcp_crawl_all_nodes.py --mode all-nodes --serial 10AE7S00HD002JK --allow-nav
  uv run python scripts/mcp_crawl_all_nodes.py --mode loop-once --allow-nav

Env: DEVICE_FARM_URL, MCP_AUTH_TOKEN / DF_LOGIN_EMAIL / DF_LOGIN_PASSWORD, DF_SERIAL
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator

_ROOT = Path(__file__).resolve().parents[1]
_REPO = _ROOT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_REPO / "device_farm") not in sys.path:
    sys.path.insert(0, str(_REPO / "device_farm"))
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from mcp_util import McpRunner  # noqa: E402

OUT_DIR = _ROOT / "debug" / "traces" / "mcp_all_nodes"
DEFAULT_SCENARIO = _ROOT / "Crawl group (2).json"
SERIAL_DEFAULT = os.environ.get("DF_SERIAL", "10AE7S00HD002JK")

# Composite step types — executed via df_run_scenario (backend scenario runner).
_SCENARIO_ONLY_TYPES = frozenset({
    "stop_app",
    "launch_app",
    "wait",
    "wait_stable",
    "if_element",
    "scroll_to",
    "loop",
    "extract",
    "fb_tap_comment_button",
    "tap_ratio",
    "swipe_ratio",
})

# Direct MCP tool per primitive step type (ratios → df_run_scenario).
_DIRECT_MCP: dict[str, str] = {
    "key": "df_key",
    "scroll_down": "df_scroll",
    "tap_selector": "df_tap_selector",
    "input_text": "df_input_text",
}


def load_scenario(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    body = raw.get("scenario", {}).get("body") or raw.get("body") or raw
    steps = body.get("steps") or []
    variables = body.get("variables") or {}
    return steps, variables


def resolve_value(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        return variables.get(key, value)
    if isinstance(value, dict):
        return {k: resolve_value(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, variables) for v in value]
    return value


def iter_scenario_steps(
    steps: list[dict[str, Any]],
    *,
    path: str = "root",
) -> Iterator[tuple[str, dict[str, Any]]]:
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        stype = step.get("type") or "?"
        step_path = f"{path}[{i}:{stype}]"
        yield step_path, step
        for branch in ("then", "else"):
            child = step.get(branch)
            if isinstance(child, list):
                yield from iter_scenario_steps(child, path=f"{step_path}.{branch}")
        if stype == "loop" and isinstance(step.get("steps"), list):
            yield from iter_scenario_steps(step["steps"], path=f"{step_path}.body")


def catalog_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, list[str]] = {}
    rows: list[dict[str, Any]] = []
    for step_path, step in iter_scenario_steps(steps):
        stype = str(step.get("type") or "?")
        by_type.setdefault(stype, []).append(step_path)
        mcp_tool = _DIRECT_MCP.get(stype)
        if stype in _SCENARIO_ONLY_TYPES:
            mcp_mode = "df_run_scenario"
        elif mcp_tool:
            mcp_mode = mcp_tool
        else:
            mcp_mode = "unknown"
        rows.append({
            "path": step_path,
            "type": stype,
            "id": step.get("id"),
            "mcp": mcp_mode,
        })
    return {
        "total_nodes": len(rows),
        "types": {t: len(paths) for t, paths in sorted(by_type.items())},
        "nodes": rows,
    }


def _strip_step_for_smoke(step: dict[str, Any]) -> dict[str, Any]:
    """Shrink long-running extract/scroll steps for smoke runs."""
    out = copy.deepcopy(step)
    if out.get("type") == "extract" and out.get("strategy") == "fb_comments":
        out["comment_scroll_passes"] = min(int(out.get("comment_scroll_passes") or 48), 4)
        out["comment_swipes_per_dump"] = min(int(out.get("comment_swipes_per_dump") or 3), 2)
        out["max_items"] = min(int(out.get("max_items") or 500), 40)
    if out.get("type") == "scroll_to":
        out["max_swipes"] = min(int(out.get("max_swipes") or 30), 3)
    if out.get("type") == "loop":
        out["count"] = 1
    return out


def build_direct_mcp_args(step: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any] | None:
    stype = step.get("type")
    resolved = resolve_value(step, variables)
    if stype == "key":
        return {"key": resolved.get("key") or "back"}
    if stype == "scroll_down":
        start_y = float(resolved.get("start_y_ratio") or 0.65)
        end_y = float(resolved.get("end_y_ratio") or 0.47)
        return {"direction": "down", "distance": max(0.1, min(1.0, start_y - end_y))}
    if stype == "tap_selector":
        sel = resolved.get("selector") or {}
        by = sel.get("by") or resolved.get("by")
        value = sel.get("value") or resolved.get("value")
        if not by or not value:
            return None
        return {"by": by, "value": value, "timeout": int(resolved.get("timeout") or 4)}
    if stype == "input_text":
        text = resolved.get("text") or resolved.get("value")
        if not text:
            return None
        return {"text": str(text)}
    return None


def analyze_xml(xml: str) -> dict[str, Any]:
    from relay.extra_data.ingest import _parse_items
    from relay.extra_data.post_comment_parity import classify_screen

    report: dict[str, Any] = {}
    t0 = time.perf_counter()
    report["classified_as"] = classify_screen(xml)
    report["classify_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    report["parse"] = {}
    for strategy in ("fb_posts", "fb_comment_target", "fb_comments"):
        t1 = time.perf_counter()
        ctx: dict[str, Any] = {}
        if strategy == "fb_comments":
            ctx["parent_post_id"] = "mcp-sim-pid"
        items, diag = _parse_items(strategy, xml, ctx)
        report["parse"][strategy] = {
            "ms": round((time.perf_counter() - t1) * 1000, 3),
            "items": len(items),
            "reason": diag.get("reason_code"),
        }
    return report


def find_loop_body(steps: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    for _, step in iter_scenario_steps(steps):
        if step.get("type") == "loop" and isinstance(step.get("steps"), list):
            return step["steps"]
    return None


def run_observe(runner: McpRunner) -> dict[str, Any]:
    """Safe MCP observe tools — no navigation."""
    tools: list[tuple[str, dict[str, Any]]] = [
        ("df_list_devices", {}),
        ("df_hierarchy", {"refresh": True}),
        ("df_get_ui_elements", {}),
        ("df_scroll", {"direction": "down", "distance": 0.12}),
    ]
    results: list[dict[str, Any]] = []
    xml: str | None = None
    for tool, args in tools:
        row = runner.call(tool, args)
        results.append(row)
        if tool == "df_hierarchy" and row.get("ok"):
            parsed = row.get("result") or {}
            xml = parsed.get("xml")

    analysis = analyze_xml(xml) if xml else None
    return {
        "mode": "observe",
        "mcp_calls": results,
        "analysis": analysis,
        "ok": all(r.get("ok") for r in results[:2]),
    }


def run_per_type_smoke(
    runner: McpRunner,
    steps: list[dict[str, Any]],
    variables: dict[str, Any],
    *,
    allow_nav: bool,
) -> dict[str, Any]:
    """One MCP invocation per step type (first occurrence in scenario)."""
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    nav_types = frozenset({
        "stop_app", "launch_app", "input_text", "tap_selector", "scroll_to", "key",
    })

    for step_path, step in iter_scenario_steps(steps):
        stype = str(step.get("type") or "?")
        if stype in seen:
            continue
        seen.add(stype)

        if not allow_nav and stype in nav_types:
            skipped.append({"type": stype, "path": step_path, "reason": "allow_nav=false"})
            continue

        smoke_step = resolve_value(_strip_step_for_smoke(step), variables)
        if stype == "loop":
            smoke_step = {
                "type": "loop",
                "count": 1,
                "steps": [{"type": "wait", "seconds": 0.3}],
                "on_error": "continue",
            }
        entry: dict[str, Any] = {"type": stype, "path": step_path}

        if stype in _SCENARIO_ONLY_TYPES:
            entry["mcp"] = "df_run_scenario"
            row = runner.call("df_run_scenario", {"steps": [smoke_step]})
            entry.update(row)
        elif stype in _DIRECT_MCP:
            tool = _DIRECT_MCP[stype]
            args = build_direct_mcp_args(smoke_step, variables)
            if args is None:
                entry["skipped"] = "missing_args"
            else:
                entry["mcp"] = tool
                row = runner.call(tool, args)
                entry.update(row)
        else:
            entry["skipped"] = "unknown_type"
            skipped.append(entry)
            continue

        # Post-action observe
        xml, hrow = runner.hierarchy(refresh=True)
        entry["post_hierarchy_ms"] = hrow.get("ms")
        if xml:
            entry["post_analysis"] = analyze_xml(xml)
        results.append(entry)

    ms_values = [r.get("ms", 0) for r in results if isinstance(r.get("ms"), (int, float))]
    return {
        "mode": "per_type_smoke",
        "types_exercised": len(results),
        "types_skipped": len(skipped),
        "avg_mcp_ms": round(statistics.mean(ms_values), 2) if ms_values else 0,
        "results": results,
        "skipped": skipped,
        "ok": all(r.get("ok", False) for r in results) if results else False,
    }


def run_loop_once(
    runner: McpRunner,
    steps: list[dict[str, Any]],
    variables: dict[str, Any],
    *,
    smoke: bool,
) -> dict[str, Any]:
    body = find_loop_body(steps)
    if not body:
        return {"mode": "loop_once", "ok": False, "error": "no_loop_body"}

    loop_steps = [
        resolve_value(_strip_step_for_smoke(s), variables) if smoke else resolve_value(s, variables)
        for s in body
    ]
    loop_step = {"type": "loop", "count": 1, "steps": loop_steps, "on_error": "continue"}

    pre_xml, _ = runner.hierarchy(refresh=True)
    pre_analysis = analyze_xml(pre_xml) if pre_xml else None

    row = runner.call("df_run_scenario", {"steps": [loop_step]})

    post_xml, _ = runner.hierarchy(refresh=True)
    post_analysis = analyze_xml(post_xml) if post_xml else None

    return {
        "mode": "loop_once",
        "smoke": smoke,
        "loop_body_steps": len(loop_steps),
        "scenario_run": row,
        "pre_analysis": pre_analysis,
        "post_analysis": post_analysis,
        "ok": row.get("ok", False),
    }


def _handler_signal(step_result: dict[str, Any]) -> dict[str, Any]:
    """Extract handler work signal (item counts) from a single step result.

    For extract steps this is the parsed/inserted comment or post count, which
    is what handler time should scale with. Transition time is everything else.
    """
    summary = step_result.get("edge_extra_summary")
    summary = summary if isinstance(summary, dict) else {}
    return {
        "type": step_result.get("type"),
        "ok": step_result.get("ok"),
        "extracted": step_result.get("extracted"),
        "duplicate_count": step_result.get("duplicate_count"),
        "parsed_count": summary.get("parsed_count"),
        "inserted_count": summary.get("inserted_count"),
        "strategy": (step_result.get("strategy")
                     or summary.get("strategy")),
    }


def run_transition(
    runner: McpRunner,
    steps: list[dict[str, Any]],
    variables: dict[str, Any],
    *,
    budget_ms: int,
) -> dict[str, Any]:
    """Phase 0: split per-step wall time into transition vs handler work.

    1. Measure a per-step MCP/scenario floor with a trivial no-op step.
    2. Run each loop-body step individually and record wall_ms + handler signal.
    3. Emit a comment_count vs comment_ms correlation for fb_comments extracts.
    Gate on the transition floor (<= budget_ms), NOT on total post time.
    """
    body = find_loop_body(steps)
    if not body:
        return {"mode": "transition", "ok": False, "error": "no_loop_body"}

    # 1) transition floor — trivial step repeated
    floor_samples: list[float] = []
    for _ in range(3):
        row = runner.call("df_run_scenario", {"steps": [{"type": "wait", "seconds": 0}]})
        ms = row.get("ms")
        if isinstance(ms, (int, float)):
            floor_samples.append(float(ms))
    floor_ms = round(statistics.median(floor_samples), 2) if floor_samples else None

    # 2) per loop-body step
    per_step: list[dict[str, Any]] = []
    comment_corr: list[dict[str, Any]] = []
    for raw in body:
        step = resolve_value(raw, variables)
        row = runner.call("df_run_scenario", {"steps": [step]})
        wall_ms = row.get("ms")
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        step_results = result.get("step_results") or []
        sig = _handler_signal(step_results[0]) if step_results else {"type": step.get("type")}
        transition_ms = None
        if isinstance(wall_ms, (int, float)) and floor_ms is not None:
            transition_ms = round(float(wall_ms) - floor_ms, 2)
        entry = {
            "type": step.get("type"),
            "strategy": step.get("strategy"),
            "wall_ms": wall_ms,
            "transition_floor_ms": floor_ms,
            "transition_overhead_ms": transition_ms,
            "handler": sig,
        }
        per_step.append(entry)
        if step.get("type") == "extract" and step.get("strategy") == "fb_comments":
            comment_corr.append({
                "comment_count": sig.get("parsed_count") or sig.get("extracted"),
                "wall_ms": wall_ms,
            })

    floor_ok = floor_ms is None or floor_ms <= budget_ms
    return {
        "mode": "transition",
        "transition_floor_ms": floor_ms,
        "transition_budget_ms": budget_ms,
        "floor_within_budget": floor_ok,
        "per_step": per_step,
        "comment_correlation": comment_corr,
        "ok": floor_ok and all(s["handler"].get("ok", True) for s in per_step),
    }


def run_all_nodes(
    runner: McpRunner,
    steps: list[dict[str, Any]],
    variables: dict[str, Any],
    *,
    allow_nav: bool,
    smoke: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "mode": "all_nodes",
        "allow_nav": allow_nav,
        "smoke": smoke,
    }
    report["catalog"] = catalog_steps(steps)
    report["observe"] = run_observe(runner)
    report["per_type"] = run_per_type_smoke(
        runner, steps, variables, allow_nav=allow_nav
    )
    if allow_nav:
        report["loop_once"] = run_loop_once(runner, steps, variables, smoke=smoke)
    else:
        report["loop_once"] = {
            "skipped": True,
            "reason": "Bật --allow-nav để chạy full loop body qua df_run_scenario",
        }
    report["ok"] = report["observe"].get("ok") and (
        report["loop_once"].get("ok", True) if allow_nav else True
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP all crawl scenario node types")
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--serial", default=SERIAL_DEFAULT)
    parser.add_argument(
        "--mode",
        choices=("catalog", "observe", "per-type", "loop-once", "all-nodes", "transition"),
        default="all-nodes",
        help="catalog=chỉ liệt kê; observe=df_hierarchy+ui; per-type=1 call/type; "
             "loop-once=1 vòng loop; transition=tách transition_ms vs handler_ms",
    )
    parser.add_argument(
        "--transition-budget-ms",
        type=int,
        default=3000,
        help="Ngưỡng transition floor cho mode=transition (gate, không phải total SLA)",
    )
    parser.add_argument(
        "--allow-nav",
        action="store_true",
        help="Cho phép tap/swipe/key/scenario steps có thể đổi màn hình",
    )
    parser.add_argument(
        "--full-extract",
        action="store_true",
        help="Không giảm comment_scroll_passes khi chạy loop (chậm)",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR / "last_report.json")
    args = parser.parse_args()

    steps, variables = load_scenario(args.scenario)
    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "serial": args.serial,
        "scenario": str(args.scenario),
        "variables": variables,
    }

    if args.mode == "catalog":
        report.update(catalog_steps(steps))
        report["ok"] = True
    else:
        runner = McpRunner(args.serial)
        try:
            smoke = not args.full_extract
            if args.mode == "observe":
                report.update(run_observe(runner))
            elif args.mode == "per-type":
                report.update(
                    run_per_type_smoke(
                        runner, steps, variables, allow_nav=args.allow_nav
                    )
                )
            elif args.mode == "transition":
                if not args.allow_nav:
                    report.update({
                        "ok": False,
                        "error": "transition mode requires --allow-nav",
                    })
                else:
                    report.update(
                        run_transition(
                            runner, steps, variables,
                            budget_ms=args.transition_budget_ms,
                        )
                    )
            elif args.mode == "loop-once":
                if not args.allow_nav:
                    report.update({
                        "ok": False,
                        "error": "loop-once requires --allow-nav",
                    })
                else:
                    report.update(
                        run_loop_once(runner, steps, variables, smoke=smoke)
                    )
            else:
                report.update(
                    run_all_nodes(
                        runner,
                        steps,
                        variables,
                        allow_nav=args.allow_nav,
                        smoke=smoke,
                    )
                )
        finally:
            runner.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
