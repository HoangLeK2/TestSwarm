#!/usr/bin/env python3
"""
Dump XML qua Device Farm MCP + giả lập các kiểu màn hình phone (fixture hoặc live).

Usage:
  cd agent-boot
  uv run python scripts/mcp_phone_scenario_sim.py --mode fixtures
  uv run python scripts/mcp_phone_scenario_sim.py --mode live --serial 10AE7S00HD002JK
  uv run python scripts/mcp_phone_scenario_sim.py --mode both

Env: DEVICE_FARM_URL, MCP_AUTH_TOKEN (dfmcp_* hoặc JWT), DF_SERIAL
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[1]
_REPO = _ROOT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_REPO / "device_farm") not in sys.path:
    sys.path.insert(0, str(_REPO / "device_farm"))

OUT_DIR = _ROOT / "debug" / "traces" / "mcp_scenario_sim"
MCP_CMD = ["sh", str(_REPO / "scripts" / "run_device_farm_mcp.sh")]

SERIAL_DEFAULT = os.environ.get("DF_SERIAL", "10AE7S00HD002JK")


def _fixture_scenarios() -> dict[str, str]:
    from relay.tests.test_comment_filter import _sheet_xml
    from relay.tests.test_post_open_resolver import _feed_card_xml

    detail_xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node text="Bài viết" bounds="[40,80][200,140]" clickable="true"/>
    <node content-desc="Bài viết của Bench Author" bounds="[40,160][900,220]"/>
    <node class="android.view.ViewGroup" content-desc="Nội dung bài viết dài để test extract posts trên detail"
          bounds="[36,300][1044,900]" clickable="true"/>
    <node class="android.widget.Button" content-desc="Nút Bình luận. Nhấn đúp để xem bình luận."
          text="Bình luận" bounds="[360,1680][520,1740]" clickable="true"/>
  </node>
</hierarchy>"""

    return {
        "group_feed_card": _feed_card_xml(
            author="Bench Author",
            metadata="2 giờ",
            body="Post body trên feed nhóm — mô phỏng recycler card",
        ),
        "post_detail": detail_xml,
        "comment_sheet_most_relevant": _sheet_xml(current_filter="most_relevant"),
        "comment_sheet_newest": _sheet_xml(current_filter="newest"),
        "comment_sheet_filter_picker": _sheet_xml(open_sort=True, current_filter="most_relevant"),
        "comment_sheet_all": _sheet_xml(current_filter="all_comments"),
    }


def _parse_tool_payload(resp: dict) -> dict | None:
    result = resp.get("result") or {}
    if result.get("isError"):
        content = result.get("content") or []
        text = (content[0].get("text") if content else "")[:500]
        return {"error": text or "mcp_tool_error"}
    content = result.get("content") or []
    if not content:
        return result if isinstance(result, dict) else None
    text = content[0].get("text") or ""
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:200]}
    if isinstance(outer, dict) and "result" in outer:
        return outer["result"]
    return outer if isinstance(outer, dict) else None


def _ensure_mcp_token() -> str:
    token = (os.environ.get("MCP_AUTH_TOKEN") or "").strip()
    if token.startswith("eyJ"):
        return token
    if token.startswith("dfmcp_"):
        from mcp.token_store import lookup_token

        if lookup_token(token) is not None:
            return token
    import urllib.request

    base = os.environ.get("DEVICE_FARM_URL", "http://localhost:8081").rstrip("/")
    email = os.environ.get("DF_LOGIN_EMAIL", "dev@gmail.com")
    password = os.environ.get("DF_LOGIN_PASSWORD", "11111111")
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
    jwt = (body.get("access_token") or "").strip()
    if not jwt:
        raise RuntimeError(f"login failed: {body}")
    return jwt


def _mcp_hierarchy(serial: str, *, refresh: bool = True) -> tuple[str | None, dict[str, Any]]:
    from mcp.client import StdIoMcpClient

    token = _ensure_mcp_token()
    os.environ["MCP_AUTH_TOKEN"] = token
    os.environ.setdefault("DEVICE_FARM_URL", "http://localhost:8081")

    t0 = time.perf_counter()
    client = StdIoMcpClient(MCP_CMD)
    try:
        resp = client.call_tool(
            "df_hierarchy",
            {"device": serial, "refresh": refresh},
        )
        payload = _parse_tool_payload(resp)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        if not payload or payload.get("error"):
            return None, {"ok": False, "ms": elapsed_ms, "error": payload}
        xml = payload.get("xml")
        if not isinstance(xml, str) or not xml.strip():
            return None, {"ok": False, "ms": elapsed_ms, "error": "empty_xml"}
        return xml, {
            "ok": True,
            "ms": elapsed_ms,
            "bytes": len(xml.encode("utf-8")),
            "element_count": payload.get("element_count"),
        }
    finally:
        client.close()


def _analyze_xml(name: str, xml: str, *, simulate_scroll: bool) -> dict[str, Any]:
    from relay.extra_data.ingest import _parse_items
    from relay.extra_data.post_comment_parity import audit_feed_post_open_taps, classify_screen
    from relay.extra_data.parsers.facebook import post_open_pipeline as pop
    from relay.extra_data.parsers.facebook.comment_filter import resolve_comment_filter_next_tap
    from relay.extra_data.parsers.facebook.parser import _hierarchy_is_fb_comment_sheet, _parse_xml

    report: dict[str, Any] = {"scenario": name, "bytes": len(xml.encode("utf-8"))}

    t0 = time.perf_counter()
    screen = classify_screen(xml)
    report["classified_as"] = screen
    report["classify_ms"] = round((time.perf_counter() - t0) * 1000, 3)

    parsers: dict[str, Callable[..., Any]] = {
        "fb_posts": lambda: _parse_items("fb_posts", xml, {}),
        "fb_comment_target": lambda: _parse_items("fb_comment_target", xml, {}),
        "fb_comments": lambda: _parse_items(
            "fb_comments", xml, {"parent_post_id": "sim-pid-001"}
        ),
    }
    report["parse"] = {}
    for strategy, fn in parsers.items():
        t1 = time.perf_counter()
        items, diag = fn()
        report["parse"][strategy] = {
            "ms": round((time.perf_counter() - t1) * 1000, 3),
            "items": len(items),
            "reason": diag.get("reason_code"),
        }

    root = _parse_xml(xml)
    report["flags"] = {
        "comment_sheet": bool(root is not None and _hierarchy_is_fb_comment_sheet(root)),
        "post_detail": pop.hierarchy_is_fb_post_detail_from_xml(xml),
    }

    if screen == "group_feed":
        t2 = time.perf_counter()
        taps = audit_feed_post_open_taps(xml, max_cards=4)
        report["tap_audit_ms"] = round((time.perf_counter() - t2) * 1000, 3)
        report["tap_audit"] = taps[:4]

    if report["flags"]["comment_sheet"]:
        t3 = time.perf_counter()
        plan = resolve_comment_filter_next_tap(xml, {"comment_filter": "all_comments"})
        report["filter_plan_ms"] = round((time.perf_counter() - t3) * 1000, 3)
        report["filter_plan_phase"] = plan.get("phase")

    if simulate_scroll and report["flags"]["comment_sheet"]:
        report["scroll_sim"] = asyncio.run(_simulate_comment_scroll(xml))

    return report


async def _simulate_comment_scroll(initial_xml: str) -> dict[str, Any]:
    from relay.extra_data.collector import collect_xml_snapshots
    from relay.tests.test_extra_data_collector import _FakeExecutor

    exec_ = _FakeExecutor(xml=initial_xml)
    ctx = {
        "comment_scroll_passes": 48,
        "comment_swipes_per_dump": 3,
        "comment_no_growth_break": 3,
        "min_comment_scan_passes": 2,
        "comment_scroll_pause_s": 0,
        "comment_recover_chrome": False,
    }
    t0 = time.perf_counter()
    snapshots, err = await collect_xml_snapshots(exec_, "sim-dev", "fb_comments", ctx)
    swipes = sum(
        1 for batch in exec_.batches for act in batch if act.get("op") == "swipe"
    )
    dumps = sum(
        1 for batch in exec_.batches for act in batch if act.get("op") == "dump_hierarchy"
    )
    return {
        "ms": round((time.perf_counter() - t0) * 1000, 2),
        "err": err,
        "snapshots": len(snapshots),
        "swipes": swipes,
        "dumps": dumps,
    }


def run_fixtures(*, simulate_scroll: bool) -> dict[str, Any]:
    scenarios = _fixture_scenarios()
    results: list[dict[str, Any]] = []
    parse_ms: list[float] = []
    for name, xml in scenarios.items():
        row = _analyze_xml(name, xml, simulate_scroll=simulate_scroll)
        results.append(row)
        parse_ms.append(sum(p["ms"] for p in row["parse"].values()))

    return {
        "mode": "fixtures",
        "count": len(results),
        "avg_parse_ms_per_scenario": round(statistics.mean(parse_ms), 3) if parse_ms else 0,
        "scenarios": results,
    }


def run_live(serial: str, *, simulate_scroll: bool) -> dict[str, Any]:
    xml, meta = _mcp_hierarchy(serial, refresh=True)
    if not xml:
        return {"mode": "live", "serial": serial, "dump": meta, "ok": False}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dump_path = OUT_DIR / f"live_{serial}_{int(time.time())}.xml"
    dump_path.write_text(xml, encoding="utf-8")

    analysis = _analyze_xml("live_device", xml, simulate_scroll=simulate_scroll)
    analysis["dump_path"] = str(dump_path)
    analysis["dump"] = meta
    return {"mode": "live", "serial": serial, "ok": True, "analysis": analysis}


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP XML dump + phone scenario simulation")
    parser.add_argument(
        "--mode",
        choices=("fixtures", "live", "both"),
        default="both",
        help="fixtures=XML giả lập; live=MCP dump device; both=cả hai",
    )
    parser.add_argument("--serial", default=SERIAL_DEFAULT)
    parser.add_argument(
        "--scroll-sim",
        action="store_true",
        help="Giả lập scroll comment trên fixture comment_sheet",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR / "last_report.json")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "serial": args.serial,
    }

    if args.mode in ("fixtures", "both"):
        report["fixtures"] = run_fixtures(simulate_scroll=args.scroll_sim)

    if args.mode in ("live", "both"):
        report["live"] = run_live(args.serial, simulate_scroll=args.scroll_sim)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(args.out)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = True
    if "live" in report:
        ok = ok and report["live"].get("ok", False)
    return 0 if ok or args.mode == "fixtures" else 1


if __name__ == "__main__":
    raise SystemExit(main())
