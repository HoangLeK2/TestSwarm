#!/usr/bin/env python3
"""
Verify FB extra-data via Device Farm MCP stdio — read-only by default (no back/swipe/tap).

Phases (same terminal, bạn điều khiển FB thủ công):
  1) Đứng trên feed nhóm → chạy script → lưu feed cache + audit tap (tránh ảnh/tên).
  2) Mở comment đúng bài (tự tay) → chạy lại → đối chiếu post ↔ comment + vẽ sơ đồ.

Env: DF_SERIAL, DEVICE_FARM_URL, DF_LOGIN_EMAIL/PASSWORD (JWT cho MCP).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT_REPO = Path(__file__).resolve().parents[2]
_AGENT_BOOT = Path(__file__).resolve().parents[1]
if str(_AGENT_BOOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_BOOT))

from relay.extra_data.post_comment_parity import (  # noqa: E402
    audit_feed_post_open_taps,
    classify_screen,
    mermaid_parity_diagram,
    verify_post_comment_parity,
)
from scripts.mcp_fb_group_walk import (  # noqa: E402
    OUT_DIR,
    _is_junk_extracted_post,
    verify_feed_posts_against_xml,
)
from relay.extra_data.parsers.facebook.feed_pipeline import parse_fb_posts_from_xml_with_diagnostic
from relay.extra_data.parsers.facebook import post_open_pipeline as pop

SERIAL = os.environ.get("DF_SERIAL", "10AE7S00HD002JK")
MIN_POSTS = int(os.environ.get("DF_MIN_POSTS", "2"))
MCP_CMD = ["sh", str(_ROOT_REPO / "scripts" / "run_device_farm_mcp.sh")]
FEED_CACHE = OUT_DIR / "mcp_feed_cache.json"


def _parse_tool_payload(resp: dict) -> dict | None:
    result = resp.get("result") or {}
    if result.get("isError"):
        content = result.get("content") or []
        if content:
            print("MCP error:", content[0].get("text", "")[:500], file=sys.stderr)
        return None
    if "tools" in result and isinstance(result.get("tools"), list):
        return result
    content = result.get("content") or []
    if not content:
        return result if result else None
    text = content[0].get("text") or ""
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(outer, dict) and "result" in outer:
        return outer["result"]
    return outer if isinstance(outer, dict) else None


def _fetch_jwt() -> str:
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
    token = (body.get("access_token") or "").strip()
    if not token:
        raise RuntimeError(f"login failed: {body}")
    return token


def _ensure_mcp_auth_token() -> str:
    token = (os.environ.get("DEVICE_FARM_MCP_TOKEN") or "").strip()
    if token.startswith("eyJ"):
        return token
    if token.startswith("dfmcp_"):
        sys.path.insert(0, str(_ROOT_REPO / "device_farm"))
        from mcp.token_store import lookup_token

        if lookup_token(token) is not None:
            return token
    jwt = _fetch_jwt()
    print("info: MCP auth = JWT (không dùng dfmcp cũ)", file=sys.stderr)
    return jwt


def _mcp_hierarchy(client, serial: str) -> str | None:
    h = _parse_tool_payload(
        client.call_tool("df_hierarchy", {"device": serial, "refresh": True})
    )
    if not isinstance(h, dict):
        return None
    xml = h.get("xml")
    return xml if isinstance(xml, str) and xml.strip() else None


def _verify_feed(xml: str, report: dict) -> tuple[list[dict], bool]:
    posts, parse_diag = parse_fb_posts_from_xml_with_diagnostic(xml, 0)
    posts = [p for p in posts if p.get("_type") != "post_stats" and not p.get("_soft_junk")]
    valid = [p for p in posts if not _is_junk_extracted_post(p)]
    node_verify = verify_feed_posts_against_xml(posts, xml, min_posts=MIN_POSTS)
    tap_audit = audit_feed_post_open_taps(xml)
    unsafe = [t for t in tap_audit if not t.get("safe_for_post_open")]

    top, _ = pop.resolve_post_open_targets_from_xml(xml)
    report["feed"] = {
        "parse_diag": parse_diag,
        "posts_parsed": len(posts),
        "valid_posts": len(valid),
        "node_verify": node_verify,
        "tap_audit": tap_audit,
        "unsafe_tap_count": len(unsafe),
        "top_tap_kind": top.get("tap_kind") if top else None,
        "posts_summary": [
            {
                "feed_item_index": p.get("feed_item_index"),
                "author": (p.get("author") or "")[:40],
                "text": (p.get("text") or "")[:72],
                "_pid": p.get("_pid"),
            }
            for p in valid
        ],
    }
    ok = bool(node_verify.get("ok")) and not unsafe
    if top and top.get("tap_kind") in ("post_media", "post_body"):
        ok = False
    return valid, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP verify extra post+comment (no auto-back)")
    parser.add_argument("--serial", default=SERIAL)
    parser.add_argument("--min-posts", type=int, default=MIN_POSTS)
    args = parser.parse_args()

    sys.path.insert(0, str(_ROOT_REPO / "device_farm"))
    from mcp.client import StdIoMcpClient

    os.environ.setdefault("DEVICE_FARM_URL", "http://localhost:8081")
    token = _ensure_mcp_auth_token()
    os.environ["DEVICE_FARM_MCP_TOKEN"] = token

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = StdIoMcpClient(MCP_CMD)
    report: dict = {
        "serial": args.serial,
        "mcp": "stdio",
        "navigation": "none",
        "note": "Script chỉ df_hierarchy — không back/swipe/tap",
    }

    try:
        xml = _mcp_hierarchy(client, args.serial)
        if not xml:
            report["ok"] = False
            report["error"] = "df_hierarchy_empty"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        screen = classify_screen(xml)
        report["screen"] = screen
        xml_path = OUT_DIR / f"mcp_screen_{screen}.xml"
        xml_path.write_text(xml, encoding="utf-8")
        report["xml_path"] = str(xml_path)

        parity = None
        feed_ok = True
        valid_posts: list[dict] = []

        if screen == "group_feed":
            valid_posts, feed_ok = _verify_feed(xml, report)
            anchor = valid_posts[0] if valid_posts else None
            cache = {
                "serial": args.serial,
                "anchor_post": anchor,
                "valid_posts": valid_posts,
            }
            FEED_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            report["feed_cache"] = str(FEED_CACHE)
            report["next_step"] = (
                "Mở comment thủ công cho anchor_post (index 0), rồi chạy lại script."
            )
            diagram = mermaid_parity_diagram(
                feed_posts=valid_posts,
                tap_audit=report["feed"].get("tap_audit") or [],
                parity=None,
                screen=screen,
            )
            report["ok"] = feed_ok

        elif screen == "comment_sheet":
            if not FEED_CACHE.is_file():
                report["ok"] = False
                report["error"] = "missing_feed_cache: chạy trên feed trước"
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1
            cache = json.loads(FEED_CACHE.read_text(encoding="utf-8"))
            anchor = cache.get("anchor_post")
            valid_posts = cache.get("valid_posts") or []
            if not anchor:
                report["ok"] = False
                report["error"] = "feed_cache_no_anchor"
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1

            from relay.extra_data.ingest import _parse_items

            comments, cdiag = _parse_items("fb_comments", xml, {"parent_post_id": anchor.get("_pid")})
            parity = verify_post_comment_parity(
                feed_post=anchor,
                comment_xml=xml,
                session_tap_pid=str(anchor.get("_pid") or ""),
            )
            report["comment"] = {
                "parse_diag": cdiag,
                "comment_count": len([c for c in comments if c.get("_type") != "post_stats"]),
                "parity": parity,
            }
            diagram = mermaid_parity_diagram(
                feed_posts=[anchor],
                tap_audit=[],
                parity=parity,
                screen=screen,
            )
            report["ok"] = bool(parity.get("ok"))

        else:
            report["ok"] = False
            report["error"] = f"unsupported_screen:{screen}"
            report["hint"] = "Đưa máy về feed nhóm hoặc sheet comment (không script back)."
            diagram = mermaid_parity_diagram(
                feed_posts=[],
                tap_audit=[],
                parity=None,
                screen=screen,
            )

        md_path = OUT_DIR / "parity_diagram.md"
        md_body = (
            "# Post ↔ Comment extra-data parity\n\n"
            f"- Serial: `{args.serial}`\n"
            f"- Screen: `{screen}`\n"
            f"- Navigation: **không** (chỉ đọc hierarchy)\n\n"
            f"{diagram}\n"
        )
        md_path.write_text(md_body, encoding="utf-8")
        report["diagram_md"] = str(md_path)

        out = OUT_DIR / f"mcp_verify_{args.serial}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(out)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
