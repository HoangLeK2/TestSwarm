#!/usr/bin/env python3
"""Scaling sweep for the relay device-registration path.

Answers one question: how many phones can a single agent-boot report before the
backend stops answering requests?

It drives the real objects — RelayServicer._handle_json, AdbRelayManager,
DeviceManager, DeviceClient.bind_relay_u2, RelayEventPump — with a synthetic
fleet, and measures the two things that made the backend look hung:

  * **max loop lag** — longest stretch the event loop could not run a task.
    An API request arriving in that window waits exactly that long.
  * **DB sessions** — the relay FSM path used to open one per phone against a
    pool of 12 + 3 overflow.

Scope, so the number is not read as more than it is: registration only. No
scrcpy, no ADB, no u2 handshake, no Postgres, no WebSocket fan-out. Those have
their own budgets (see benchmark_stream_100_phone_suite.py). This is the path
that froze on agent-boot startup, and nothing else.

    uv run python scripts/benchmark_relay_registration.py
    uv run python scripts/benchmark_relay_registration.py --sizes 100,500,2000
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import resource
import sys
import time

from core.config import Config
from runtime.core.device_client import DeviceClient
from runtime.core.device_manager import DeviceManager
from runtime.transports import adb_relay_server
from runtime.transports.adb_relay_server import AdbRelayManager
from runtime.transports.grpc_relay_server import RelayServicer
from runtime.transports.relay_event_pump import RelayEventPump

DEFAULT_SIZES = (50, 100, 250, 500, 1000, 2000)


class _StubSession:
    def __init__(self, counter) -> None:
        self._counter = counter

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def commit(self) -> None:
        self._counter.commits += 1


class _SessionCounter:
    def __init__(self) -> None:
        self.opened = 0
        self.commits = 0

    def __call__(self) -> _StubSession:
        self.opened += 1
        return _StubSession(self)


class _LoopLag:
    def __init__(self) -> None:
        self.samples: list[float] = []
        self._task = None
        self._stop = False

    async def _run(self) -> None:
        last = time.perf_counter()
        while not self._stop:
            await asyncio.sleep(0)
            now = time.perf_counter()
            self.samples.append((now - last) * 1000.0)
            last = now

    async def __aenter__(self):
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)
        self.samples.clear()
        return self

    async def __aexit__(self, *_exc):
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return False

    @property
    def max_ms(self) -> float:
        return max(self.samples) if self.samples else 0.0


def _fleet(size: int) -> tuple[list[str], list[dict]]:
    """USB-style serials: no IP embedded, so wlan_ip must come from caps."""
    serials = [f"BENCH{i:06d}USB" for i in range(size)]
    caps = [
        {
            "serial": s,
            "wlan_ip": f"10.{i // 65024}.{(i // 254) % 254}.{(i % 254) + 1}",
            "brand": "bench",
            "model": "probe",
            "has_u2": False,
        }
        for i, s in enumerate(serials)
    ]
    return serials, caps


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux reports kilobytes.
    return usage / (1024 * 1024) if sys.platform == "darwin" else usage / 1024


async def _run_one(size: int, *, index_file: str) -> dict:
    config = Config()
    config.device.index_file = index_file
    device_manager = DeviceManager(config)
    relay = AdbRelayManager()

    async def _no_redis(*_a, **_k) -> None:
        return None

    relay._sync_relay_to_redis = _no_redis
    relay._sync_caps_to_redis = _no_redis
    # bind_relay_u2 resolves the relay through the module singleton.
    adb_relay_server._manager = relay

    counter = _SessionCounter()
    applied: list[str] = []

    async def _apply_online(serial, *, logical_serial=None, hardware_serial=None, db=None):
        applied.append(serial)
        return True

    async def _apply_offline(serial, *, logical_serial=None, hardware_serial=None, db=None):
        return True

    pump = RelayEventPump(
        session_factory=counter,
        apply_online=_apply_online,
        apply_offline=_apply_offline,
        batch_max=64,
        coalesce_ms=20,
    )
    await pump.start()

    def _on_online(serial: str) -> None:
        pump.submit("online", serial)
        caps = relay.get_capabilities(serial) or {}
        device = device_manager.register_relay_device(serial)
        device.set_event_loop(asyncio.get_event_loop())
        device.on_agent_status({"state": "READY"})
        host = str(caps.get("wlan_ip") or "").strip() or None
        device.bind_relay_u2(serial, host=host)

    relay.set_on_device_online(_on_online)

    servicer = RelayServicer(relay, api_key=None)
    ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=256)
    serials, caps = _fleet(size)

    relay_id, conn = await servicer._handle_json(
        {"type": "register", "relay_id": "bench-relay", "serials": []},
        "bench-agent", ctrl_q, None, None,
    )

    rss_before = _rss_mb()
    heartbeat = {"type": "heartbeat", "serials": serials, "capabilities": caps}

    async with _LoopLag() as lag:
        started = time.perf_counter()
        await servicer._handle_json(heartbeat, "bench-agent", ctrl_q, relay_id, conn)
        blocked_ms = (time.perf_counter() - started) * 1000.0

        drain_started = time.perf_counter()
        deadline = drain_started + 60.0
        while len(applied) < size and time.perf_counter() < deadline:
            await asyncio.sleep(0.005)
        drain_ms = (time.perf_counter() - drain_started) * 1000.0

    stats = pump.stats()
    await pump.stop()

    result = {
        "phones": size,
        "blocked_ms": blocked_ms,
        "max_lag_ms": lag.max_ms,
        "drain_ms": drain_ms,
        "db_sessions": counter.opened,
        "batches": stats["batches"],
        "dropped": stats["dropped"],
        "high_water": stats["high_water"],
        "applied": len(applied),
        "registered": len(device_manager.devices),
        "rss_delta_mb": max(0.0, _rss_mb() - rss_before),
    }

    device_manager.teardown_all()
    adb_relay_server._manager = None
    del device_manager, relay, servicer
    gc.collect()
    return result


async def _main(args: argparse.Namespace) -> int:
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    # bind_relay_u2 spawns one waiter thread per device. Stub it: it runs off
    # the event loop by design and would only try to reach phones that do not
    # exist. Thread-count behaviour is covered by
    # test_relay_callback_blocking_guard.py instead.
    DeviceClient._relay_u2_bind_wait_connect = lambda self, serial: None

    print(
        "\nrelay device-registration scaling sweep"
        "\n(registration path only — no scrcpy / ADB / u2 / Postgres)\n"
    )
    header = (
        f"{'phones':>7} {'blocked p50':>13} {'blocked max':>13} {'lag p50':>9} "
        f"{'drain':>9} {'db sess':>8} {'dropped':>8} {'queue hw':>9} {'rss +MB':>8}"
    )
    print(header)
    print("-" * len(header))

    results = []
    for size in sizes:
        # Thread-creation cost on the loop is noisy enough that a single trial
        # swings by 5x. Report the median of several and keep the worst.
        trials = [await _run_one(size, index_file=args.index_file) for _ in range(args.repeat)]
        blocked = sorted(t["blocked_ms"] for t in trials)
        lags = sorted(t["max_lag_ms"] for t in trials)
        result = dict(trials[-1])
        result["blocked_ms"] = blocked[len(blocked) // 2]
        result["blocked_worst_ms"] = blocked[-1]
        result["max_lag_ms"] = lags[len(lags) // 2]
        result["max_lag_worst_ms"] = lags[-1]
        results.append(result)
        print(
            f"{result['phones']:>7} "
            f"{result['blocked_ms']:>11.1f}ms "
            f"{result['blocked_worst_ms']:>11.1f}ms "
            f"{result['max_lag_ms']:>7.1f}ms "
            f"{result['drain_ms']:>7.1f}ms "
            f"{result['db_sessions']:>8} "
            f"{result['dropped']:>8} "
            f"{result['high_water']:>9} "
            f"{result['rss_delta_mb']:>8.1f}",
            flush=True,
        )
        if result["applied"] != size or result["registered"] != size:
            print(
                f"  ! incomplete: applied={result['applied']} "
                f"registered={result['registered']} of {size} "
                f"(dropped={result['dropped']} — raise DEVICE_FARM_RELAY_FSM_QUEUE_MAX)",
                file=sys.stderr,
            )

    budget = args.max_lag_ms
    worst = max(results, key=lambda r: r["max_lag_worst_ms"])
    print(
        f"\nworst loop stall: {worst['max_lag_worst_ms']:.1f}ms at {worst['phones']} phones "
        f"(budget {budget:.0f}ms)"
    )
    within = [
        r["phones"] for r in results
        if r["max_lag_worst_ms"] <= budget and not r["dropped"]
    ]
    if within:
        print(f"largest fleet within budget: {max(within)} phones")
    else:
        print("no tested fleet size stayed within budget", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--sizes", default=",".join(str(s) for s in DEFAULT_SIZES),
        help="comma-separated fleet sizes to sweep",
    )
    parser.add_argument("--index-file", default="/tmp/bench_device_index.json")
    parser.add_argument("--repeat", type=int, default=5, help="trials per size; median reported")
    parser.add_argument(
        "--max-lag-ms", type=float, default=200.0,
        help="event-loop stall budget — above this the API is visibly unresponsive",
    )
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
