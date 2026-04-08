# Phase 01 — U2 Session Pool (agent-boot)

## Context Links

- Current HTTP proxy: `agent-boot/relay/agent.py:407-483` (`_handle_u2_request`, `_do_u2_http`)
- Device state machine: `agent-boot/relay/device_state.py` (`DeviceRegistry`, OFFLINE transitions)
- Scrcpy session TTL reference: `agent-boot/relay/session_manager.py:21` (`SESSION_TTL=300s`)

## Overview

**Priority:** P1 — foundation for all subsequent phases  
**Status:** Pending  

Introduce a persistent, per-device `uiautomator2.Device` session pool inside
agent-boot so that subsequent actions reuse a warm connection to port 9008
(falling back to 7912 atx-agent) instead of opening a new `urllib` request
every call.

## Key Insights

- Current flow: `urllib.request → HTTP POST to device:7912/jsonrpc/0`. A new
  connection is established per call.
- `uiautomator2` Python library maintains a persistent HTTP keep-alive to
  atx-agent (port 7912) or the u2 server (port 9008), eliminating per-call TCP
  setup.
- agent-boot already pools scrcpy sessions with a 300-second TTL; same pattern
  applies here.
- `u2.connect(serial)` works for USB; `u2.connect_wifi("ip")` for TCP/IP devices.

## Requirements

- Thread-safe: `get_session(serial)` called from multiple async tasks concurrently
- Lazy connect: no connection created until first `get_session` call
- Health check: detect dead sessions before handing to executor
- Eviction: idle ≥ 300 s evicted; OFFLINE device immediately evicted
- Feature-gated: entire pool behind `U2_BATCH_ENABLED` env var (default off)

## Related Code Files

| File | Action | Description |
|------|--------|-------------|
| `agent-boot/relay/u2_session_pool.py` | CREATE | `U2SessionPool` class |
| `agent-boot/relay/agent.py` | MODIFY | Import + instantiate pool; wire eviction on OFFLINE |
| `agent-boot/pyproject.toml` | MODIFY | Add `uiautomator2>=3.0` dependency |

## Architecture

```
U2SessionPool
  ├── _sessions: dict[serial → _Entry]
  ├── _global_lock: asyncio.Lock          # guards _sessions mutations
  │
  ├── get_session(serial) → Device        # lazy connect; reuse if alive
  ├── evict(serial)                        # called on device OFFLINE
  ├── start() / stop()                     # lifecycle hooks
  │
  └── _reap_loop() [background task]      # evict idle entries every 30s
        └── criterion: (now - last_used) > 300s
```

## Implementation Steps

```python
# agent-boot/relay/u2_session_pool.py

import asyncio, logging, time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS     = 300.0
PING_INTERVAL_SECONDS   = 30.0
CONNECT_TIMEOUT_SECONDS = 8.0

@dataclass
class _Entry:
    device:    object
    last_used: float
    lock:      asyncio.Lock = field(default_factory=asyncio.Lock)
    serial:    str          = ""

class U2SessionPool:
    def __init__(self, loop: asyncio.AbstractEventLoop,
                 connect_fn=None):          # injectable for tests
        self._loop          = loop
        self._connect_fn    = connect_fn    # defaults to uiautomator2.connect
        self._sessions: dict[str, _Entry] = {}
        self._global_lock   = asyncio.Lock()
        self._reaper_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._reaper_task = self._loop.create_task(self._reap_loop())

    async def stop(self) -> None:
        if self._reaper_task:
            self._reaper_task.cancel()
        async with self._global_lock:
            for entry in self._sessions.values():
                self._close_blocking(entry)
            self._sessions.clear()

    async def get_session(self, serial: str):
        async with self._global_lock:
            entry = self._sessions.get(serial)
        if entry is None:
            entry = await self._connect(serial)
        async with entry.lock:
            if not await self._is_alive(entry):
                await self._reconnect(entry)
            entry.last_used = time.monotonic()
        return entry.device

    async def evict(self, serial: str) -> None:
        async with self._global_lock:
            entry = self._sessions.pop(serial, None)
        if entry:
            self._close_blocking(entry)
            logger.info("u2-pool: evicted serial=%s", serial)

    # ---------- internals ----------

    async def _connect(self, serial: str) -> _Entry:
        import uiautomator2 as u2          # lazy import
        fn = self._connect_fn or u2.connect
        host = serial.rsplit(":", 1)[0] if ":" in serial else serial
        dev = await asyncio.wait_for(
            self._loop.run_in_executor(None, fn, host),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        entry = _Entry(device=dev, last_used=time.monotonic(), serial=serial)
        async with self._global_lock:
            # Double-check: another task may have connected while we waited
            if serial not in self._sessions:
                self._sessions[serial] = entry
            else:
                self._close_blocking(entry)  # discard duplicate
                entry = self._sessions[serial]
        logger.info("u2-pool: connected serial=%s", serial)
        return entry

    async def _reconnect(self, entry: _Entry) -> None:
        self._close_blocking(entry)
        import uiautomator2 as u2
        fn = self._connect_fn or u2.connect
        host = entry.serial.rsplit(":", 1)[0] if ":" in entry.serial else entry.serial
        entry.device = await self._loop.run_in_executor(None, fn, host)
        logger.info("u2-pool: reconnected serial=%s", entry.serial)

    async def _is_alive(self, entry: _Entry) -> bool:
        try:
            return bool(
                await self._loop.run_in_executor(
                    None, lambda: entry.device.alive
                )
            )
        except Exception as exc:
            logger.debug("u2-pool: ping failed serial=%s err=%s", entry.serial, exc)
            return False

    def _close_blocking(self, entry: _Entry) -> None:
        try:
            if hasattr(entry.device, "stop"):
                entry.device.stop()
        except Exception:
            pass

    async def _reap_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                now = time.monotonic()
                stale: list[str] = []
                async with self._global_lock:
                    for s, e in self._sessions.items():
                        if now - e.last_used > SESSION_TTL_SECONDS:
                            stale.append(s)
                for s in stale:
                    await self.evict(s)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("u2-pool: reaper error %s", exc)
```

## Integration into `agent-boot/relay/agent.py`

```python
from .u2_session_pool import U2SessionPool

# Agent.__init__:
import os
self._u2_batch_enabled = os.getenv("U2_BATCH_ENABLED", "").lower() in ("1", "true")
self._u2_pool: Optional[U2SessionPool] = (
    U2SessionPool(loop=asyncio.get_event_loop())
    if self._u2_batch_enabled else None
)

# Agent.start():
if self._u2_pool:
    await self._u2_pool.start()

# Agent.stop():
if self._u2_pool:
    await self._u2_pool.stop()

# Device OFFLINE callback (inside _on_device_event or DeviceRegistry callback):
if self._u2_pool and state == "offline":
    asyncio.create_task(self._u2_pool.evict(serial))
```

## Todo List

- [ ] Create `agent-boot/relay/u2_session_pool.py`
- [ ] Add `uiautomator2>=3.0` to `[project.dependencies]` in `agent-boot/pyproject.toml`
- [ ] Lazy-import `uiautomator2` (cold-start stays fast when flag off)
- [ ] Instantiate pool in `Agent.__init__` guarded by `U2_BATCH_ENABLED`
- [ ] Start reaper in `Agent.start()`, stop in `Agent.stop()`
- [ ] Wire `pool.evict(serial)` on device OFFLINE transitions
- [ ] Add double-check in `_connect()` to prevent duplicate entries under concurrency
- [ ] Document `U2_BATCH_ENABLED` in `agent-boot/.env.example` and README

## Success Criteria

- `get_session(serial)` called twice returns same device object (no double connect)
- `evict(serial)` stops device and removes entry
- Idle session evicted by reaper after 300 s
- Dead session (`alive=False`) transparently reconnected on next call

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| `uiautomator2` import fails (not installed) | Lazy import; catch `ImportError`, disable pool, log ERROR |
| `u2.connect()` hangs | `asyncio.wait_for(timeout=8s)` aborts it |
| Race: two coroutines connect same serial | Double-check in `_connect()` after acquiring `_global_lock` |

## Security Considerations

- No auth changes — pool reuses existing device IP trust model
- Pool only connects to device IPs already known via ADB (no untrusted input)
