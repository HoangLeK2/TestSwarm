"""Run the agent stream SLO matrix without requiring physical phones."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from relay.stream_slo_harness import (
    MockFleetConfig,
    StreamSloThresholds,
    run_mock_isolation_probe,
)


def _parse_phone_counts(raw: str) -> tuple[int, ...]:
    counts = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not counts or any(count <= 1 for count in counts):
        raise argparse.ArgumentTypeError(
            "phone counts must contain integers greater than one"
        )
    return counts


async def _run(args: argparse.Namespace) -> dict[str, object]:
    thresholds = StreamSloThresholds(
        handoff_p95_ms=args.handoff_p95_ms,
        queue_age_p95_ms=args.queue_age_p95_ms,
        idr_recovery_p95_ms=args.idr_recovery_p95_ms,
    )
    results: list[dict[str, object]] = []
    for phones in args.phones:
        report = await run_mock_isolation_probe(
            MockFleetConfig(
                phones=phones,
                duration_s=args.duration_s,
                fps=args.fps,
                payload_bytes=args.payload_bytes,
                idr_response_ms=args.idr_response_ms,
                command_interval_s=args.command_interval_s,
                consumer_delay_ms=args.consumer_delay_ms,
                visible_phones=args.visible_phones or None,
                video_shards=args.video_shards,
            ),
            noisy_fps_multiplier=args.noisy_fps_multiplier,
            max_normal_phone_p95_delta_ms=args.isolation_p95_delta_ms,
            thresholds=thresholds,
        )
        results.append(
            {
                "phones": phones,
                "passed": report.passed,
                "baseline": asdict(report.baseline),
                "noisy_run": asdict(report.noisy_run),
                "isolation": {
                    "noisy_serial": report.noisy_serial,
                    "allowed_p95_delta_ms": report.allowed_p95_delta_ms,
                    "max_normal_phone_handoff_p95_delta_ms": (
                        report.max_normal_phone_handoff_p95_delta_ms
                    ),
                    "max_normal_phone_queue_age_p95_delta_ms": (
                        report.max_normal_phone_queue_age_p95_delta_ms
                    ),
                    "max_normal_phone_p95_delta_ms": (
                        report.max_normal_phone_p95_delta_ms
                    ),
                    "normal_phones_within_slo": (
                        report.normal_phones_within_slo
                    ),
                },
            }
        )
    return {
        "kind": "mock_stream_slo_matrix",
        "passed": all(bool(result["passed"]) for result in results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise agent stream SLOs with production-shaped phones",
    )
    parser.add_argument(
        "--phones",
        type=_parse_phone_counts,
        default=(30, 60, 120),
        help="comma-separated fleet sizes (default: 30,60,120)",
    )
    parser.add_argument("--duration-s", type=float, default=1.5)
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--payload-bytes", type=int, default=50_000)
    parser.add_argument("--idr-response-ms", type=float, default=100.0)
    parser.add_argument("--command-interval-s", type=float, default=0.25)
    parser.add_argument("--consumer-delay-ms", type=float, default=0.0)
    parser.add_argument(
        "--visible-phones",
        type=int,
        default=0,
        help="phones with active H264 video; 0 means every phone streams video",
    )
    parser.add_argument(
        "--video-shards",
        type=int,
        default=8,
        help="physical video shard queues/streams; 0 forces legacy shared queue",
    )
    parser.add_argument("--noisy-fps-multiplier", type=float, default=8.0)
    parser.add_argument("--handoff-p95-ms", type=float, default=10.0)
    parser.add_argument("--queue-age-p95-ms", type=float, default=50.0)
    parser.add_argument("--idr-recovery-p95-ms", type=float, default=300.0)
    parser.add_argument("--isolation-p95-delta-ms", type=float, default=5.0)
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
