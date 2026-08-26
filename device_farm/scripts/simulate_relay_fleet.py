#!/usr/bin/env python3
"""Fake agent-boot: register N phones over real gRPC and measure API freeze.

What it does
------------
Opens a real ``RelayService.Stream`` to a running backend, sends the same
``register`` + ``heartbeat`` JSON an agent-boot sends, and reports a synthetic
fleet. While that happens, a second task polls ``GET /api/health`` and reports
the latency distribution and the longest gap with no response at all.

That gap is the number that matters: it is what a user sees as "the backend is
hung while agent-boot starts".

    uv run python scripts/simulate_relay_fleet.py \\
        --grpc localhost:50051 --http http://localhost:8000 --phones 100

What it does NOT reproduce
--------------------------
No scrcpy, no ADB, no u2 — the phones do not exist, so nothing that depends on
talking to a device runs. It covers the registration path only, which is where
the startup freeze lives. Pair it with a real-device canary before making a
production claim.

Point this at staging, not production: the backend will create in-memory
DeviceClient entries and slot assignments for every fake serial. They disappear
when the stream closes, but the slot-index file keeps their history.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import grpc

from runtime.transports.grpc_gen import relay_pb2, relay_pb2_grpc

FAKE_RELAY_PREFIX = "simfleet"


def _fleet(count: int, *, style: str, prefix: str = FAKE_RELAY_PREFIX) -> tuple[list[str], list[dict]]:
    serials: list[str] = []
    caps: list[dict] = []
    for i in range(count):
        if style == "usb":
            # No IP in the serial — wlan_ip must come from capabilities. This is
            # the shape that triggered the original 2s-per-phone stall.
            serial = f"{prefix.upper()}{i:05d}USB"
        else:
            serial = f"10.243.{i // 254}.{(i % 254) + 1}:5555"
        serials.append(serial)
        caps.append(
            {
                "serial": serial,
                "wlan_ip": f"10.243.{i // 254}.{(i % 254) + 1}",
                "wlan_cidr": "10.243.0.0/16",
                "brand": "simulated",
                "model": "fleet-probe",
                "android_version": "13",
                "sdk": 33,
                "screen_width": 1080,
                "screen_height": 2400,
                "has_u2": False,
                "has_stf": False,
            }
        )
    return serials, caps


async def _poll_health(
    http_base: str, stop: asyncio.Event, interval_s: float
) -> tuple[list[float], float]:
    """Return (latencies_ms, longest_silence_ms)."""
    import aiohttp

    latencies: list[float] = []
    longest_silence = 0.0
    url = f"{http_base.rstrip('/')}/api/health"
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        last_ok = time.perf_counter()
        while not stop.is_set():
            started = time.perf_counter()
            try:
                async with session.get(url) as resp:
                    await resp.read()
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                latencies.append(elapsed_ms)
                now = time.perf_counter()
                longest_silence = max(longest_silence, (now - last_ok) * 1000.0)
                last_ok = now
            except Exception:
                # A timeout IS the symptom — keep the clock running.
                pass
            await asyncio.sleep(interval_s)
    return latencies, longest_silence


async def _run_agent(
    grpc_target: str,
    api_key: str,
    serials: list[str],
    caps: list[dict],
    hold_s: float,
    heartbeat_s: float,
) -> None:
    metadata = [("x-agent-id", f"{FAKE_RELAY_PREFIX}-agent")]
    if api_key:
        metadata.append(("x-relay-api-key", api_key))

    async with grpc.aio.insecure_channel(grpc_target) as channel:
        stub = relay_pb2_grpc.RelayServiceStub(channel)
        outbox: asyncio.Queue = asyncio.Queue()

        async def _requests():
            while True:
                item = await outbox.get()
                if item is None:
                    return
                yield relay_pb2.AgentMsg(meta=json.dumps(item).encode())

        call = stub.Stream(_requests(), metadata=metadata)
        acked = asyncio.Event()
        stream_error: list[BaseException] = []

        async def _drain_responses() -> None:
            # Never swallow this. An earlier version caught and dropped every
            # exception here, so a backend rejecting the stream outright
            # (UNAUTHENTICATED — missing --api-key) still produced a confident
            # "OK: longest silence 206ms" while the backend received nothing.
            try:
                async for msg in call:
                    if getattr(msg, "is_json", False):
                        acked.set()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — reported, not hidden
                stream_error.append(exc)
                acked.set()

        drain = asyncio.create_task(_drain_responses())

        # agent-boot registers with an empty serial list — it never blocks
        # registration on ADB — then the watcher reports the fleet.
        await outbox.put(
            {
                "type": "register",
                "relay_id": f"{FAKE_RELAY_PREFIX}-relay",
                "serials": [],
                "version": "sim-1.0",
            }
        )
        # Refuse to report a fleet into a stream the backend never accepted —
        # otherwise the run reports latency for an idle backend.
        try:
            await asyncio.wait_for(acked.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "backend never acknowledged the relay register — no measurement is possible"
            ) from None
        if stream_error:
            raise RuntimeError(f"relay stream rejected: {stream_error[0]}") from stream_error[0]

        print(f"  → reporting {len(serials)} phones …", flush=True)
        heartbeat = {"type": "heartbeat", "serials": serials, "capabilities": caps}
        await outbox.put(heartbeat)

        deadline = time.perf_counter() + hold_s
        while time.perf_counter() < deadline:
            await asyncio.sleep(heartbeat_s)
            await outbox.put(heartbeat)

        await outbox.put(None)
        drain.cancel()
        try:
            await drain
        except asyncio.CancelledError:
            pass
        if stream_error:
            raise RuntimeError(f"relay stream failed mid-run: {stream_error[0]}")


async def _main(args: argparse.Namespace) -> int:
    serials, caps = _fleet(args.phones, style=args.serial_style, prefix=args.serial_prefix)
    stop = asyncio.Event()

    print(f"polling {args.http}/api/health every {args.poll_interval}s …", flush=True)
    poller = asyncio.create_task(_poll_health(args.http, stop, args.poll_interval))
    await asyncio.sleep(2.0)  # baseline samples before the fleet arrives

    started = time.perf_counter()
    try:
        await _run_agent(
            args.grpc, args.api_key, serials, caps, args.hold, args.heartbeat_interval
        )
    finally:
        stop.set()
    registration_s = time.perf_counter() - started
    latencies, longest_silence = await poller

    if not latencies:
        print("no health responses at all — is the backend up?", file=sys.stderr)
        return 2

    latencies.sort()

    def _pct(p: float) -> float:
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return latencies[idx]

    print(
        f"\n── /api/health during registration of {args.phones} phones ──\n"
        f"  samples            : {len(latencies)}\n"
        f"  p50                : {_pct(0.50):8.1f} ms\n"
        f"  p95                : {_pct(0.95):8.1f} ms\n"
        f"  p99                : {_pct(0.99):8.1f} ms\n"
        f"  max                : {latencies[-1]:8.1f} ms\n"
        f"  mean               : {statistics.fmean(latencies):8.1f} ms\n"
        f"  longest silence    : {longest_silence:8.1f} ms   <— the freeze\n"
        f"  agent stream wall  : {registration_s:8.1f} s\n"
    )
    print(
        "Check GET /api/relay/status → relay_fsm_pump for queue depth and drops.\n"
        f"A healthy run keeps 'longest silence' near the poll interval "
        f"({args.poll_interval * 1000:.0f}ms).",
    )

    budget_ms = args.max_silence_ms
    if longest_silence > budget_ms:
        print(
            f"\nFAIL: backend went silent for {longest_silence:.0f}ms "
            f"(budget {budget_ms:.0f}ms).",
            file=sys.stderr,
        )
        return 1
    print(f"\nOK: longest silence {longest_silence:.0f}ms within {budget_ms:.0f}ms.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grpc", default="localhost:50051", help="backend gRPC relay host:port")
    parser.add_argument("--http", default="http://localhost:8000", help="backend HTTP base URL")
    parser.add_argument("--api-key", default="", help="x-relay-api-key, if the backend requires one")
    parser.add_argument("--phones", type=int, default=100, help="fleet size to report")
    parser.add_argument(
        "--serial-prefix", default=FAKE_RELAY_PREFIX,
        help="vary this between runs — a serial the backend already registered "
             "is not new work, and reusing one silently measures an idle path",
    )
    parser.add_argument(
        "--serial-style",
        choices=["usb", "tcp"],
        default="usb",
        help="usb = serial carries no IP (the shape that triggered the freeze)",
    )
    parser.add_argument("--hold", type=float, default=20.0, help="seconds to keep the stream open")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument(
        "--max-silence-ms",
        type=float,
        default=2000.0,
        help="exit non-zero if the backend stops answering for longer than this",
    )
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
