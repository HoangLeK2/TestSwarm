"""Fleet-registration simulation — reproduces the agent-boot startup freeze.

What this simulates
-------------------
agent-boot connecting and reporting a 100-phone fleet, driven through the real
objects on the real path:

    RelayServicer._handle_json  (gRPC transport, real)
      → AdbRelayManager.update_serials / update_capabilities  (real)
        → device-online callback  (mirrors web/server.py:_on_relay_device_online)
          → DeviceManager.register_relay_device  (real, incl. slot persistence)
          → DeviceClient.bind_relay_u2           (real)
          → RelayEventPump.submit                (real)

No phones and no Postgres: the DB session is a stub, and the off-loop u2 waiter
thread is stubbed out (it is allowed to be slow — it does not run on the loop).
Everything that *did* block the loop is real.

What it measures
----------------
1. **Event-loop lag** — a background task ticking with ``asyncio.sleep(0)``
   records the worst gap between ticks. That gap is exactly what an API request
   experiences as "the backend is hung". The original bug produced ~2000ms per
   phone here.
2. **DB sessions opened** — the second freeze mechanism was one session per
   serial against a pool of 12+3. The pump must keep this at a handful.

Run it directly for a readable report::

    uv run pytest tests/test_relay_fleet_registration_perf.py -s

Budgets are overridable via env (see tests/perf_assertions.py:perf_budget).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from core.config import Config
from runtime.core.device_client import DeviceClient
from runtime.core.device_manager import DeviceManager
from runtime.transports.adb_relay_server import AdbRelayManager
from runtime.transports.grpc_relay_server import RelayServicer
from runtime.transports.relay_event_pump import RelayEventPump
from tests.perf_assertions import percentile, perf_budget

FLEET_SIZE = 100


class _StubSession:
    """Stands in for AsyncSessionLocal() — counts opens and commits."""

    def __init__(self, counter: "_SessionCounter") -> None:
        self._counter = counter

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *_exc) -> bool:
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


class _LoopLagRecorder:
    """Sample the gap between consecutive event-loop ticks."""

    def __init__(self) -> None:
        self.samples_ms: list[float] = []
        self._task: asyncio.Task | None = None
        self._stop = False

    async def _run(self) -> None:
        last = time.perf_counter()
        while not self._stop:
            await asyncio.sleep(0)
            now = time.perf_counter()
            self.samples_ms.append((now - last) * 1000.0)
            last = now

    async def __aenter__(self) -> "_LoopLagRecorder":
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)
        self.samples_ms.clear()
        return self

    async def __aexit__(self, *_exc) -> bool:
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
        return max(self.samples_ms) if self.samples_ms else 0.0

    def p95_ms(self) -> float:
        return percentile(self.samples_ms, 0.95)


def _fleet(size: int) -> tuple[list[str], list[dict]]:
    """USB-style serials — no IP embedded, so wlan_ip must come from caps.

    This is the shape that triggered the bug: with an ip:port serial the host
    can be parsed out of the serial itself and the poll loop was skipped.
    """
    serials = [f"R58M{i:05d}USB" for i in range(size)]
    caps = [
        {
            "serial": s,
            "wlan_ip": f"192.168.{i // 254}.{(i % 254) + 1}",
            "brand": "samsung",
            "model": "SM-N975F",
            "has_u2": False,
        }
        for i, s in enumerate(serials)
    ]
    return serials, caps


@pytest.mark.asyncio
async def test_fleet_registration_keeps_the_api_loop_responsive(tmp_path, monkeypatch, capsys):
    # The u2 bind waiter is deliberately off the event loop; stub it so the
    # harness does not attempt real HTTP to phones that do not exist.
    monkeypatch.setattr(
        DeviceClient, "_relay_u2_bind_wait_connect", lambda self, serial: None
    )

    config = Config()
    config.device.index_file = str(tmp_path / "device_index.json")
    device_manager = DeviceManager(config)

    relay = AdbRelayManager()

    async def _no_redis(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(relay, "_sync_relay_to_redis", _no_redis)
    monkeypatch.setattr(relay, "_sync_caps_to_redis", _no_redis)
    # bind_relay_u2 resolves the relay through the module singleton, not through
    # whatever manager the caller holds. Without this the harness silently
    # exercises nothing: bind_relay_u2 returns False on its first line.
    monkeypatch.setattr("runtime.transports.adb_relay_server._manager", relay)

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

    # Mirror web/server.py:_on_relay_device_online — the parts that run on the
    # event loop. scrcpy attach and bootstrap are omitted: both are dispatched
    # to a thread pool / task and never blocked the loop.
    def _on_relay_device_online(serial: str) -> None:
        pump.submit("online", serial)
        caps = relay.get_capabilities(serial) or {}
        device = device_manager.register_relay_device(serial)
        device.set_event_loop(asyncio.get_event_loop())
        device.on_agent_status({"state": "READY"})
        host = str(caps.get("wlan_ip") or "").strip() or None
        device.bind_relay_u2(serial, host=host)

    relay.set_on_device_online(_on_relay_device_online)

    servicer = RelayServicer(relay, api_key=None)
    ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=256)
    serials, caps = _fleet(FLEET_SIZE)

    # 1) agent-boot connects and registers with an empty serial list (its real
    #    startup shape — registration never waits on ADB).
    relay_id, conn = await servicer._handle_json(
        {"type": "register", "relay_id": "sim-relay", "serials": []},
        "sim-agent", ctrl_q, None, None,
    )

    # 2) the device watcher finds the fleet and the first heartbeat carries it.
    heartbeat = {"type": "heartbeat", "serials": serials, "capabilities": caps}

    async with _LoopLagRecorder() as lag:
        started = time.perf_counter()
        await servicer._handle_json(heartbeat, "sim-agent", ctrl_q, relay_id, conn)
        register_ms = (time.perf_counter() - started) * 1000.0

        # Let the pump drain while still watching the loop.
        deadline = time.perf_counter() + 5.0
        while len(applied) < FLEET_SIZE and time.perf_counter() < deadline:
            await asyncio.sleep(0.01)

    await pump.stop()

    stats = pump.stats()
    report = (
        f"\n── fleet registration simulation ({FLEET_SIZE} phones) ──\n"
        f"  handle_heartbeat wall   : {register_ms:8.1f} ms\n"
        f"  event-loop lag  max     : {lag.max_ms:8.1f} ms\n"
        f"  event-loop lag  p95     : {lag.p95_ms():8.1f} ms\n"
        f"  DB sessions opened      : {counter.opened:8d}  (one per phone = the old bug)\n"
        f"  DB commits              : {counter.commits:8d}\n"
        f"  FSM events applied      : {len(applied):8d}\n"
        f"  pump batches            : {stats['batches']:8d}\n"
        f"  pump dropped            : {stats['dropped']:8d}\n"
        f"  devices registered      : {len(device_manager.devices):8d}\n"
    )
    print(report)

    assert len(device_manager.devices) == FLEET_SIZE
    assert len(applied) == FLEET_SIZE, "pump did not drain the fleet"
    assert stats["dropped"] == 0

    # ── The two freeze mechanisms ──
    max_lag_budget = perf_budget("RELAY_FLEET_MAX_LOOP_LAG_MS", 500.0)
    assert lag.max_ms <= max_lag_budget, (
        f"event loop stalled {lag.max_ms:.0f}ms registering {FLEET_SIZE} phones "
        f"(budget {max_lag_budget:.0f}ms). The API is unresponsive for that long. "
        f"{report}"
    )

    session_budget = int(perf_budget("RELAY_FLEET_MAX_DB_SESSIONS", 8))
    assert counter.opened <= session_budget, (
        f"{counter.opened} DB sessions for {FLEET_SIZE} phones (budget {session_budget}). "
        f"The pool is 12+3 — this drains it and every API request blocks on "
        f"pool_timeout. {report}"
    )


@pytest.mark.asyncio
async def test_fleet_registration_survives_a_flapping_relay(tmp_path, monkeypatch):
    """Repeated heartbeats with the same fleet must not redo the work.

    A relay whose connection flaps re-sends its full serial list. Registration
    is only new-serial work, so the second heartbeat should be nearly free —
    otherwise every flap re-freezes the backend.
    """
    monkeypatch.setattr(
        DeviceClient, "_relay_u2_bind_wait_connect", lambda self, serial: None
    )

    config = Config()
    config.device.index_file = str(tmp_path / "device_index.json")
    device_manager = DeviceManager(config)
    relay = AdbRelayManager()

    async def _no_redis(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(relay, "_sync_relay_to_redis", _no_redis)
    monkeypatch.setattr(relay, "_sync_caps_to_redis", _no_redis)
    # bind_relay_u2 resolves the relay through the module singleton, not through
    # whatever manager the caller holds. Without this the harness silently
    # exercises nothing: bind_relay_u2 returns False on its first line.
    monkeypatch.setattr("runtime.transports.adb_relay_server._manager", relay)

    online_calls: list[str] = []

    def _on_online(serial: str) -> None:
        online_calls.append(serial)
        device = device_manager.register_relay_device(serial)
        device.set_event_loop(asyncio.get_event_loop())
        device.bind_relay_u2(serial)

    relay.set_on_device_online(_on_online)

    servicer = RelayServicer(relay, api_key=None)
    ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=256)
    serials, caps = _fleet(FLEET_SIZE)

    relay_id, conn = await servicer._handle_json(
        {"type": "register", "relay_id": "sim-relay", "serials": []},
        "sim-agent", ctrl_q, None, None,
    )
    heartbeat = {"type": "heartbeat", "serials": serials, "capabilities": caps}
    await servicer._handle_json(heartbeat, "sim-agent", ctrl_q, relay_id, conn)
    assert len(online_calls) == FLEET_SIZE

    async with _LoopLagRecorder() as lag:
        for _ in range(5):
            await servicer._handle_json(heartbeat, "sim-agent", ctrl_q, relay_id, conn)

    assert len(online_calls) == FLEET_SIZE, "steady-state heartbeat re-ran registration"
    assert lag.max_ms <= perf_budget("RELAY_FLEET_STEADY_LOOP_LAG_MS", 100.0), (
        f"steady-state heartbeats stalled the loop for {lag.max_ms:.0f}ms"
    )
