from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from relay.extra_data.parsers.facebook import post_open_pipeline


def _many_feed_cards_xml(count: int) -> str:
    cards: list[str] = []
    for idx in range(count):
        y = 260 + idx * 360
        cards.append(
            f"""
      <node class="android.view.ViewGroup" bounds="[0,{y}][1080,{y + 320}]">
        <node class="android.widget.TextView" text="Author {idx}" bounds="[132,{y + 20}][520,{y + 64}]" clickable="false"/>
        <node class="android.widget.TextView" text="{idx} giờ" bounds="[132,{y + 72}][280,{y + 108}]" clickable="true"/>
        <node class="android.view.ViewGroup" content-desc="Post body {idx} for opening detail view" bounds="[36,{y + 130}][1044,{y + 230}]" clickable="true" focusable="true"/>
        <node class="android.widget.Button" content-desc="Nút Bình luận" text="Bình luận" bounds="[360,{y + 250}][520,{y + 310}]" clickable="true"/>
      </node>"""
        )
    height = max(2400, 620 + count * 360)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,{height}]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,200][1080,{height - 200}]">
{''.join(cards)}
    </node>
  </node>
</hierarchy>"""


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) < 20:
        return max(values)
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def _bench(
    label: str,
    xml: str,
    iterations: int,
    *,
    clear_each: bool,
    **kwargs,
) -> dict[str, float | int | str]:
    post_open_pipeline._POST_OPEN_RESOLVE_CACHE.clear()
    timings: list[float] = []
    for _ in range(iterations):
        if clear_each:
            post_open_pipeline._POST_OPEN_RESOLVE_CACHE.clear()
        started = time.perf_counter()
        top, _alts = post_open_pipeline.resolve_post_open_targets_from_xml(xml, **kwargs)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if top is None:
            raise RuntimeError(f"{label}: no post target resolved")
        timings.append(elapsed_ms)
    return {
        "mode": label,
        "iterations": iterations,
        "p50_ms": statistics.median(timings),
        "p95_ms": _p95(timings),
        "max_ms": max(timings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Facebook post-open target resolver.")
    parser.add_argument("--cards", type=int, default=80)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--xml", type=Path)
    args = parser.parse_args()

    xml = args.xml.read_text(encoding="utf-8") if args.xml else _many_feed_cards_xml(args.cards)
    rows = [
        _bench(
            "full_scan_cold",
            xml,
            args.iterations,
            clear_each=True,
            max_scan_elements=0,
        ),
        _bench(
            "bounded_scan_cold",
            xml,
            args.iterations,
            clear_each=True,
            max_scan_elements=12,
        ),
        _bench(
            "bounded_scan_cache",
            xml,
            args.iterations,
            clear_each=False,
            max_scan_elements=12,
        ),
    ]

    print("mode,iterations,p50_ms,p95_ms,max_ms")
    for row in rows:
        print(
            f"{row['mode']},{row['iterations']},"
            f"{row['p50_ms']:.3f},{row['p95_ms']:.3f},{row['max_ms']:.3f}"
        )


if __name__ == "__main__":
    main()
