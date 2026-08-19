#!/usr/bin/env python3
"""Measure whether short control activities wait behind long device work.

This is the experiment that motivated splitting the task queues. On a single
shared queue, saturating the activity slots with long work delayed a 34ms
activity by 20.5 seconds — and finalize_campaign, the activity that releases a
device claim, is one of those short ones. The phone stayed marked busy for the
whole wait, so the fleet lost capacity exactly when it was most loaded.

The script floods the device queue, then times how long a probe takes to *start*
on each queue:

  device queue  — expected to stay slow; that is the queue being saturated
  control queue — expected to stay fast; that is the point of the split

Usage (host, Temporal published on :7233):

  cd device_farm
  ./.venv/bin/python scripts/stress_temporal_head_of_line.py
  ./.venv/bin/python scripts/stress_temporal_head_of_line.py --flood 140 --hold-ms 25000

Env:
  TEMPORAL_SERVER_URL           default localhost:7233
  TEMPORAL_NAMESPACE            default default
  TEMPORAL_TASK_QUEUE           default device-scenario
  TEMPORAL_CONTROL_TASK_QUEUE   default device-control
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

from temporalio.client import Client


async def _start_probe(
    client: Client,
    workflow_queue: str,
    delay_ms: int,
    tag: str,
    activity_queue: str | None = None,
):
    """Start a probe workflow, optionally routing its activity elsewhere.

    Control workers register activities only, so a workflow cannot be started on
    the control queue. Routing the activity instead is also the shape the real
    control activities use, which makes this measure the production path.
    """
    return await client.start_workflow(
        "CapacityProbeWorkflow",
        {"delay_ms": delay_ms, "task_queue": activity_queue},
        id=f"hol-{tag}-{uuid.uuid4().hex[:10]}",
        task_queue=workflow_queue,
    )


async def _measure(
    client: Client, workflow_queue: str, tag: str, activity_queue: str | None = None
) -> dict:
    """Time one short probe end to end, and report its Temporal queue wait."""
    started = time.perf_counter()
    handle = await _start_probe(client, workflow_queue, 50, tag, activity_queue)
    result = await handle.result()
    return {
        "queue": activity_queue or workflow_queue,
        "schedule_to_start_ms": round(float(result.get("schedule_to_start_ms", 0.0)), 1),
        "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
    }


async def async_main(args: argparse.Namespace) -> int:
    client = await Client.connect(args.server, namespace=args.namespace)

    print(f"server={args.server} device_queue={args.task_queue} control_queue={args.control_task_queue}")

    baseline = await _measure(client, args.task_queue, "baseline")
    print(
        f"baseline (idle queue):        schedule_to_start={baseline['schedule_to_start_ms']:>9.1f} ms"
    )

    print(f"flooding {args.flood} activities of {args.hold_ms} ms on {args.task_queue} ...")
    flood = [
        await _start_probe(client, args.task_queue, args.hold_ms, f"flood{i}")
        for i in range(args.flood)
    ]
    # Give the workers time to actually pick the flood up and fill every slot.
    await asyncio.sleep(args.settle_s)

    # Probe both queues concurrently so they see the same instant of saturation.
    device, control = await asyncio.gather(
        _measure(client, args.task_queue, "probe-device"),
        _measure(
            client,
            args.task_queue,
            "probe-control",
            activity_queue=args.control_task_queue,
        ),
    )
    print(
        f"under load, device queue:     schedule_to_start={device['schedule_to_start_ms']:>9.1f} ms"
    )
    print(
        f"under load, control queue:    schedule_to_start={control['schedule_to_start_ms']:>9.1f} ms"
    )

    print("draining flood ...")
    await asyncio.gather(*[h.result() for h in flood])

    ok = control["schedule_to_start_ms"] <= args.control_budget_ms
    verdict = "PASS" if ok else "FAIL"
    print(
        f"{verdict} control queue stayed under {args.control_budget_ms} ms "
        f"while the device queue was at {device['schedule_to_start_ms']:.0f} ms"
    )

    if args.json_output:
        payload = {
            "baseline": baseline,
            "under_load_device": device,
            "under_load_control": control,
            "flood": args.flood,
            "hold_ms": args.hold_ms,
            "control_budget_ms": args.control_budget_ms,
            "pass": ok,
        }
        with open(args.json_output, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"wrote {args.json_output}")

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.environ.get("TEMPORAL_SERVER_URL", "localhost:7233"))
    parser.add_argument("--namespace", default=os.environ.get("TEMPORAL_NAMESPACE", "default"))
    parser.add_argument(
        "--task-queue", default=os.environ.get("TEMPORAL_TASK_QUEUE", "device-scenario")
    )
    parser.add_argument(
        "--control-task-queue",
        default=os.environ.get("TEMPORAL_CONTROL_TASK_QUEUE", "device-control"),
    )
    parser.add_argument("--flood", type=int, default=140, help="long activities to queue up")
    parser.add_argument("--hold-ms", type=int, default=25000, help="how long each flood item holds a slot")
    parser.add_argument("--settle-s", type=float, default=4.0, help="wait for the flood to occupy slots")
    parser.add_argument(
        "--control-budget-ms",
        type=float,
        default=200.0,
        help="pass threshold for the control queue",
    )
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
