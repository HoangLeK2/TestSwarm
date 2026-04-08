# Phase 04 — device_farm Client Integration

## Context Links

- `_RelaySession` (existing): `device_farm/runtime/transports/u2_jsonrpc.py:60-114`
- `AdbRelayManager.u2_http()`: `device_farm/runtime/transports/adb_relay_server.py:671-689`
- `_reconnect_u2_atx()`: `device_farm/runtime/core/device_client.py:2014-2083`
- `tap_selector()`: `device_farm/runtime/core/device_client.py:1615-1672` — currently 3 RPCs

## Overview

**Priority:** P1  
**Status:** Pending  
**Blocked by:** Phase 01, 02, 03

Expose `u2_batch` and `u2_flow` to `device_farm` callers and migrate the
hot path (`tap_selector`) to use `u2_flow("find_click_wait")`.

Legacy `u2_http()` stays completely untouched.

## Key Insights

- `AdbRelayManager` already has a correlation table for `u2_request` / `u2_result`; extract it into a shared `_request_reply()` so all three message types share one waiter table.
- `_RelaySession` (sync adapter) stays unchanged — it wraps `u2_http()`. A parallel `_BatchRelaySession` wraps `u2_batch()` + `u2_flow()`.
- `tap_selector()` currently calls 3 JSON-RPCs: `waitForExists` + `objInfo` + `click`. With `find_click_wait` flow this becomes 1 RPC.
- Feature flag `U2_BATCH_ENABLED` (env + config) guards all new paths.

## Related Code Files

| File | Action | Description |
|------|--------|-------------|
| `device_farm/runtime/transports/adb_relay_server.py` | MODIFY | Extract `_request_reply()`; add `u2_batch()`, `u2_flow()` |
| `device_farm/runtime/transports/u2_jsonrpc.py` | MODIFY | Add `_BatchRelaySession` adapter |
| `device_farm/runtime/core/device_client.py` | MODIFY | Instantiate `_BatchRelaySession`; migrate `tap_selector`; add `u2_batch()` helper |

## Architecture

### Refactor: `_request_reply()` in `AdbRelayManager`

```python
# device_farm/runtime/transports/adb_relay_server.py

import itertools
_id_counter = itertools.count(1)

class AdbRelayManager:
    def _next_id(self) -> str:
        return f"rr-{next(_id_counter)}"

    async def _request_reply(
        self,
        serial:      str,
        msg:         dict,
        reply_type:  str,
        req_id:      str,
        timeout:     float = 30.0,
    ) -> dict:
        """Send a JSON command; await matching reply by id + type."""
        conn = self.relay_for_serial(serial)
        fut: asyncio.Future = self._loop.create_future()
        self._pending[req_id] = (reply_type, fut)
        try:
            await conn.send_json(msg)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(req_id, None)

    # Incoming message router (call from relay stream reader):
    def _on_agent_meta(self, meta: dict) -> None:
        req_id = meta.get("id", "")
        entry = self._pending.get(req_id)
        if entry:
            expected_type, fut = entry
            if meta.get("type") == expected_type and not fut.done():
                fut.set_result(meta)
```

### New Methods on `AdbRelayManager`

```python
async def u2_batch(
    self,
    serial:     str,
    actions:    list[dict],
    early_exit: bool  = True,
    timeout:    float = 30.0,
) -> dict:
    if not actions:
        return {"ok": True, "stopped_at": None, "results": [], "error": None}
    req_id = self._next_id()
    return await self._request_reply(
        serial=serial,
        msg={
            "type": "u2_batch", "id": req_id, "serial": serial,
            "schema": 1, "early_exit": early_exit, "actions": actions,
        },
        reply_type="u2_batch_result", req_id=req_id, timeout=timeout,
    )

async def u2_flow(
    self,
    serial:  str,
    flow:    str,
    params:  dict,
    timeout: float = 30.0,
) -> dict:
    req_id = self._next_id()
    return await self._request_reply(
        serial=serial,
        msg={
            "type": "u2_flow", "id": req_id, "serial": serial,
            "flow": flow, "params": params,
        },
        reply_type="u2_flow_result", req_id=req_id, timeout=timeout,
    )
```

### `_BatchRelaySession` Adapter

```python
# device_farm/runtime/transports/u2_jsonrpc.py

class _BatchRelaySession:
    """
    Sync adapter for u2_batch / u2_flow over the relay.
    Mirrors _RelaySession for the batch/flow surface.
    """
    def __init__(self, mgr, serial: str, loop: asyncio.AbstractEventLoop):
        self._mgr    = mgr
        self._serial = serial
        self._loop   = loop

    def batch(self, actions: list[dict], timeout: float = 30.0) -> list[dict]:
        fut = asyncio.run_coroutine_threadsafe(
            self._mgr.u2_batch(self._serial, actions, timeout=timeout),
            self._loop,
        )
        res = fut.result(timeout=timeout + 5.0)
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "u2_batch failed")
        return res.get("results") or []

    def flow(self, name: str, params: dict, timeout: float = 30.0) -> dict:
        fut = asyncio.run_coroutine_threadsafe(
            self._mgr.u2_flow(self._serial, name, params, timeout=timeout),
            self._loop,
        )
        res = fut.result(timeout=timeout + 5.0)
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or f"u2_flow {name!r} failed")
        return res.get("value") or {}
```

### `device_client.py` Changes

#### In `_reconnect_u2_atx()`, add batch session alongside existing u2 session:

```python
# After existing `self._u2 = d_rpc` assignment
if _batch_enabled():
    _rm = get_relay_manager()
    if _rm:
        self._u2_batch = _BatchRelaySession(_rm, self._adb_serial or host, self._loop)
    else:
        self._u2_batch = None
```

#### `_selector_dict(by, value)` — maps existing `by` names to JSON selector:

```python
_BY_MAP = {
    "xpath":        "xpath",
    "resourceId":   "resourceId",
    "text":         "text",
    "description":  "description",
    "className":    "className",
}

def _selector_dict(self, by: str, value: str) -> dict:
    key = _BY_MAP.get(by)
    if key is None:
        # Unknown by type — fall back to text match
        return {"text": value}
    return {key: value}
```

#### `tap_selector()` migration (keep legacy renamed `_tap_selector_legacy`):

```python
def tap_selector(self, by: str, value: str) -> None:
    if self._batch_enabled() and self._u2_batch is not None:
        try:
            result = self._u2_batch.flow(
                "find_click_wait",
                {
                    "selector":      self._selector_dict(by, value),
                    "click_timeout": 10.0,
                    "gone_timeout":  2.0,
                },
                timeout=15.0,
            )
            if result.get("found"):
                self.hierarchy_invalidate_cache()
                return
            # element not found — fall through to legacy
            self._log(f"tap_selector: not found via flow {by}={value!r}", logging.DEBUG)
        except Exception as exc:
            # Backward compat: log and fall back
            self._log(f"tap_selector flow error: {exc} — falling back", logging.WARNING)
    self._tap_selector_legacy(by, value)

def _tap_selector_legacy(self, by: str, value: str) -> None:
    # ... existing implementation unchanged ...
```

#### `u2_batch()` convenience helper:

```python
def u2_batch(self, actions: list[dict], timeout: float = 30.0) -> list[dict]:
    """Pipeline N primitive u2 ops in a single RPC. Raises if not enabled."""
    if not self._batch_enabled() or self._u2_batch is None:
        raise RuntimeError("u2 batch not available for this device")
    return self._u2_batch.batch(actions, timeout=timeout)
```

## Implementation Checklist

- [ ] Refactor `u2_http()` correlation logic into `_request_reply()` — ensure existing tests pass
- [ ] Add `u2_batch()` + `u2_flow()` to `AdbRelayManager`
- [ ] Add `_BatchRelaySession` in `u2_jsonrpc.py`
- [ ] Add `_selector_dict()` in `device_client.py`
- [ ] Instantiate `_u2_batch` in `_reconnect_u2_atx()` when feature enabled
- [ ] Rename existing `tap_selector` implementation to `_tap_selector_legacy`
- [ ] Add new `tap_selector` with flow path + fallback
- [ ] Add `u2_batch()` convenience helper
- [ ] Add `U2_BATCH_ENABLED` to `config.yaml` with default `false`
- [ ] Log once per device on connect whether batch path is active
- [ ] Handle backward compat: if agent-boot responds with `ok=false, error="unsupported"`, fallback to legacy and log WARNING once

## Backward Compatibility

If agent-boot is older (predates phase 02), it either:
- Ignores the unknown message type → client times out after 30 s → falls back to `_tap_selector_legacy`
- Returns `ok=false, error="unsupported"` (if phase 02 added that safeguard)

Either way the behavior degrades gracefully. The one-time WARNING in logs signals that agent-boot needs updating.

## Edge Cases

- `_request_reply` concurrent calls: use `req_id` as key in `_pending` dict — each call has unique ID, safe
- `u2_batch(actions=[])` → returns immediately, no gRPC call
- `_batch_enabled()` returns `False` if relay not connected → `_u2_batch` stays `None` → falls through to legacy
- Device resets: `_u2_batch` is re-created on next `_reconnect_u2_atx()` call (same lifecycle as `_u2`)

## Security Considerations

No new auth surface — same gRPC stream, same relay trust model.
