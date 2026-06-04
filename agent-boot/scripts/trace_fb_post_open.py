#!/usr/bin/env python3
"""Dump FB feed hierarchy from device (u2) and diagnose post-open tap targets.

Cursor has no device MCP — this script is the supported dump/analyze path.
Writes XML + JSON analysis under agent-boot/debug/traces/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from relay.extra_data.parsers.facebook import post_open_pipeline as pop  # noqa: E402
from relay.extra_data.parsers.facebook.comment_pipeline import (  # noqa: E402
    _is_tappable_fb_node,
    _parse_bounds_from_node,
)
from relay.extra_data.parsers.facebook.parser import (  # noqa: E402
    _collect_text_nodes,
    _parse_bounds,
    _parse_xml,
)


def _dump_from_device(serial: str | None) -> str:
    import uiautomator2 as u2

    dev = u2.connect(serial)
    return dev.dump_hierarchy(compressed=False)


def _default_out_dir() -> Path:
    return _ROOT / "debug" / "traces"


def _analyze_cards(xml: str) -> list[dict[str, object]]:
    root = _parse_xml(xml)
    if root is None:
        return []
    rows: list[dict[str, object]] = []
    for idx, element in pop._discover_post_open_scan_elements(root):
        cb = _parse_bounds(element)
        nodes = _collect_text_nodes(element, toolbar_cutoff_y=0)
        ab = pop._find_author_bounds(nodes, cb) if cb and nodes else None
        body = (
            pop._find_post_body_tap(
                element, card_bounds=cb, author_bounds=ab, nodes=nodes
            )
            if cb and ab
            else None
        )
        media = (
            pop._find_post_media_tap(
                element, card_bounds=cb, author_bounds=ab, nodes=nodes
            )
            if cb
            else None
        )
        tap = (
            pop._pick_header_tap_for_card(
                element, card_bounds=cb, nodes=nodes, author_bounds=ab
            )
            if cb
            else None
        )
        header_taps: list[dict[str, object]] = []
        if cb:
            gx1, gy1, gx2, gy2 = cb
            for node in element.iter("node"):
                if not _is_tappable_fb_node(node):
                    continue
                b = _parse_bounds_from_node(node)
                if not b or b[1] > gy1 + int((gy2 - gy1) * 0.35):
                    continue
                label = pop._node_label(node)
                if not label:
                    continue
                header_taps.append(
                    {
                        "bounds": list(b),
                        "text": (node.get("text") or "")[:80],
                        "content_desc": (node.get("content-desc") or "")[:80],
                        "label": label[:100],
                    }
                )
        row: dict[str, object] = {
            "feed_item_index": idx,
            "card_bounds": list(cb) if cb else None,
            "author_bounds": list(ab) if ab else None,
            "pick": None,
            "tap_point": None,
            "header_tappable": header_taps[:12],
        }
        if tap and cb:
            bounds = tuple(tap["bounds"])
            cx, cy = pop.post_header_tap_point(
                bounds, tap_kind=str(tap.get("tap_kind") or "")
            )
            row["pick"] = {
                "tap_kind": tap.get("tap_kind"),
                "bounds": list(bounds),
                "label": (tap.get("label") or "")[:120],
            }
            row["tap_point"] = [cx, cy]
        row["post_body_candidate"] = (
            {"bounds": list(body["bounds"]), "label": body.get("label")}
            if body
            else None
        )
        row["post_media_candidate"] = (
            {"bounds": list(media["bounds"]), "label": media.get("label")}
            if media
            else None
        )
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--serial", "-s", help="ADB serial (default: u2 auto-pick)")
    ap.add_argument("--xml", type=Path, help="Analyze existing hierarchy XML instead of dumping")
    ap.add_argument(
        "--out",
        type=Path,
        default=_default_out_dir(),
        help="Directory to save dumps (default: agent-boot/debug/traces)",
    )
    ap.add_argument("--no-save", action="store_true", help="Do not write XML to disk")
    args = ap.parse_args()

    xml_path: Path | None = args.xml
    if xml_path:
        xml = xml_path.read_text(encoding="utf-8")
        print(f"loaded {xml_path} ({len(xml.encode('utf-8'))} bytes)")
    else:
        xml = _dump_from_device(args.serial)
        if not args.no_save:
            args.out.mkdir(parents=True, exist_ok=True)
            tag = args.serial or "auto"
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            xml_path = args.out / f"fb_feed_{tag}_{ts}.xml"
            xml_path.write_text(xml, encoding="utf-8")
            print(f"saved {xml_path} ({len(xml.encode('utf-8'))} bytes)")

    diag = pop.diagnose_post_open_resolution(xml)
    top, ranked = pop.resolve_post_open_targets_from_xml(xml)
    card_analysis = _analyze_cards(xml)
    report: dict[str, object] = {
        "xml_path": str(xml_path) if xml_path else None,
        "diagnostic": diag,
        "top_target": None,
        "tap_point": None,
        "alternates": [],
        "cards": card_analysis,
    }
    if top:
        bounds = tuple(top["bounds"])
        cx, cy = pop.post_header_tap_point(
            bounds, tap_kind=str(top.get("tap_kind") or "")
        )
        report["top_target"] = {
            k: top.get(k)
            for k in (
                "tap_kind",
                "bounds",
                "tap_label",
                "score",
                "feed_item_index",
            )
        }
        report["tap_point"] = [cx, cy]
    for alt in ranked[:5]:
        report["alternates"].append(
            {
                "tap_kind": alt.get("tap_kind"),
                "bounds": alt.get("bounds"),
                "feed_item_index": alt.get("feed_item_index"),
                "score": alt.get("score"),
            }
        )

    if xml_path and not args.no_save:
        analysis_path = xml_path.with_suffix(".analysis.json")
        analysis_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"analysis {analysis_path}")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if top is None:
        print("\nFAIL: no post-open tap target", file=sys.stderr)
        return 1
    print(
        f"\nOK: tap ({report['tap_point'][0]}, {report['tap_point'][1]}) "
        f"kind={top.get('tap_kind')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
