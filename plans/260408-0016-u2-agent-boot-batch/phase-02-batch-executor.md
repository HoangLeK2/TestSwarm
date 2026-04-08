# Phase 02 — Batch Executor (`u2_batch`)

## Context Links

- Session pool: `phase-01-u2-session-pool.md`
- Current single-action handler: `agent-boot/relay/agent.py:407-483`
- Existing dispatch: `agent-boot/relay/agent.py` — search `"type"` field switch

## Overview

**Priority:** P1  
**Status:** Pending  
**Blocked by:** Phase 01

Accept a list of primitive uiautomator2 actions in a single gRPC message,
execute them sequentially against the pooled `uiautomator2.Device`, and
return an aggregated result list in one response.

## Key Insights

- No proto changes: rides existing `ControlMsg(is_json=true)` envelope.
  The `type` field discriminates: `"u2_request"` (legacy) vs `"u2_batch"` (new).
- All blocking ops run in `loop.run_in_executor(None, ...)` — asyncio loop never blocks.
- `early_exit=true` (default) stops on first failure, returns `stopped_at` index.
- Unknown ops return `ok=false` without crashing the dispatcher.

## Wire Schema

**Request** (sent as `ControlMsg.data`, `is_json=true`):
```json
{
  "type":       "u2_batch",
  "id":         "req-123",
  "serial":     "192.168.1.10:5555",
  "schema":     1,
  "early_exit": true,
  "actions": [
    {"op": "click",      "x": 540, "y": 960},
    {"op": "exists",     "selector": {"text": "OK"}},
    {"op": "get_text",   "selector": {"resourceId": "com.app:id/title"}},
    {"op": "wait_gone",  "selector": {"text": "Loading..."}, "timeout": 5.0}
  ]
}
```

**Response** (sent as `AgentMsg.meta`, JSON):
```json
{
  "type":       "u2_batch_result",
  "id":         "req-123",
  "ok":         true,
  "stopped_at": null,
  "results": [
    {"op": "click",    "ok": true},
    {"op": "exists",   "ok": true,  "value": true},
    {"op": "get_text", "ok": true,  "value": "Welcome"},
    {"op": "wait_gone","ok": true}
  ],
  "error": null
}
```

**On failure with `early_exit=true`:**
```json
{
  "type":       "u2_batch_result",
  "id":         "req-123",
  "ok":         false,
  "stopped_at": 2,
  "results": [
    {"op": "click",    "ok": true},
    {"op": "exists",   "ok": true,  "value": false},
    {"op": "get_text", "ok": false, "error": "selector not found"}
  ],
  "error": "action[2] get_text: selector not found"
}
```

## Supported Primitive Ops

| op               | required keys                          | returns         |
|------------------|----------------------------------------|-----------------|
| `click`          | `x`, `y`                               | —               |
| `long_click`     | `x`, `y`, `duration?`                  | —               |
| `swipe`          | `fx`, `fy`, `tx`, `ty`, `duration?`    | —               |
| `exists`         | `selector`                             | `bool`          |
| `get_text`       | `selector`                             | `str`           |
| `set_text`       | `selector`, `text`                     | —               |
| `press_key`      | `key`                                  | —               |
| `wait_exists`    | `selector`, `timeout`                  | `bool`          |
| `wait_gone`      | `selector`, `timeout`                  | `bool`          |
| `dump_hierarchy` | `compressed?`                          | `str` (xml)     |
| `screenshot`     | `format?` (png/jpeg)                   | `str` (base64)  |

**Selector forms:**
```json
{"text":"OK"}
{"resourceId":"com.app:id/btn"}
{"description":"Submit"}
{"xpath":"//android.widget.Button[@text='OK']"}
{"className":"android.widget.Button", "instance":0}
```

## Related Code Files

| File | Action | Description |
|------|--------|-------------|
| `agent-boot/relay/u2_executor.py` | CREATE | `U2Executor` class + op table |
| `agent-boot/relay/agent.py` | MODIFY | Add `u2_batch` dispatch branch + `_handle_u2_batch()` |

## Architecture

```python
# agent-boot/relay/u2_executor.py

import asyncio, base64, logging
from .u2_session_pool import U2SessionPool

logger = logging.getLogger(__name__)

def _resolve(dev, selector: dict):
    """Map JSON selector dict → uiautomator2 UiObject or XPath selector."""
    if not selector:
        raise ValueError("selector required")
    if "xpath" in selector:
        return dev.xpath(selector["xpath"])
    kwargs = {k: v for k, v in selector.items() if k in (
        "text","textContains","textStartsWith","textMatches",
        "description","descriptionContains","descriptionStartsWith",
        "resourceId","className","packageName","instance","index",
    )}
    if not kwargs:
        raise ValueError(f"unrecognised selector keys: {list(selector)}")
    return dev(**kwargs)

# --- blocking op implementations (run in executor) ---

def _op_click(dev, act):
    dev.click(int(act["x"]), int(act["y"]))

def _op_long_click(dev, act):
    dev.long_click(int(act["x"]), int(act["y"]), float(act.get("duration", 0.5)))

def _op_swipe(dev, act):
    dev.swipe(int(act["fx"]), int(act["fy"]),
              int(act["tx"]), int(act["ty"]),
              duration=float(act.get("duration", 0.2)))

def _op_exists(dev, act):
    return bool(_resolve(dev, act.get("selector", {})).exists)

def _op_get_text(dev, act):
    obj = _resolve(dev, act.get("selector", {}))
    if not obj.exists:
        raise RuntimeError("selector not found")
    return obj.get_text() if hasattr(obj, "get_text") else obj.info.get("text", "")

def _op_set_text(dev, act):
    _resolve(dev, act.get("selector", {})).set_text(act.get("text", ""))

def _op_press_key(dev, act):
    dev.press(act["key"])

def _op_wait_exists(dev, act):
    return bool(_resolve(dev, act["selector"]).wait(timeout=float(act.get("timeout", 5))))

def _op_wait_gone(dev, act):
    return bool(_resolve(dev, act["selector"]).wait_gone(timeout=float(act.get("timeout", 5))))

def _op_dump(dev, act):
    return dev.dump_hierarchy(compressed=bool(act.get("compressed", False)))

def _op_screenshot(dev, act):
    png = dev.screenshot(format="raw")
    return base64.b64encode(png).decode("ascii")

_OP_TABLE = {
    "click":           _op_click,
    "long_click":      _op_long_click,
    "swipe":           _op_swipe,
    "exists":          _op_exists,
    "get_text":        _op_get_text,
    "set_text":        _op_set_text,
    "press_key":       _op_press_key,
    "wait_exists":     _op_wait_exists,
    "wait_gone":       _op_wait_gone,
    "dump_hierarchy":  _op_dump,
    "screenshot":      _op_screenshot,
}

class U2Executor:
    def __init__(self, pool: U2SessionPool, loop: asyncio.AbstractEventLoop):
        self._pool = pool
        self._loop = loop

    async def run_batch(
        self,
        serial:     str,
        actions:    list[dict],
        early_exit: bool = True,
    ) -> dict:
        if not actions:
            return {"ok": True, "stopped_at": None, "results": [], "error": None}

        try:
            dev = await self._pool.get_session(serial)
        except Exception as exc:
            return {"ok": False, "stopped_at": 0, "results": [],
                    "error": f"session unavailable: {exc}"}

        results: list[dict] = []
        for idx, act in enumerate(actions):
            op = act.get("op", "")
            fn = _OP_TABLE.get(op)
            if fn is None:
                entry = {"op": op, "ok": False, "error": f"unknown op: {op}"}
                results.append(entry)
                if early_exit:
                    return {"ok": False, "stopped_at": idx, "results": results,
                            "error": f"action[{idx}] unknown op: {op}"}
                continue
            try:
                value = await self._loop.run_in_executor(None, fn, dev, act)
                entry = {"op": op, "ok": True}
                if value is not None:
                    entry["value"] = value
                results.append(entry)
            except Exception as exc:
                results.append({"op": op, "ok": False, "error": str(exc)})
                if early_exit:
                    return {"ok": False, "stopped_at": idx, "results": results,
                            "error": f"action[{idx}] {op}: {exc}"}
        return {"ok": True, "stopped_at": None, "results": results, "error": None}
```

## Agent Dispatch Hook

```python
# agent-boot/relay/agent.py  (add alongside existing "u2_request" branch)

elif mtype == "u2_batch":
    asyncio.create_task(self._handle_u2_batch(msg, send_queue))

async def _handle_u2_batch(self, msg: dict, send_queue: asyncio.Queue) -> None:
    if self._u2_executor is None:
        result = {"ok": False, "stopped_at": 0, "results": [],
                  "error": "u2 batch not enabled"}
    else:
        result = await self._u2_executor.run_batch(
            serial     = msg.get("serial", ""),
            actions    = msg.get("actions") or [],
            early_exit = bool(msg.get("early_exit", True)),
        )
    result["type"] = "u2_batch_result"
    result["id"]   = msg.get("id", "")
    await send_queue.put(json.dumps(result).encode())
```

## Todo List

- [ ] Create `agent-boot/relay/u2_executor.py` with `U2Executor` + op table + `_resolve()`
- [ ] Validate `act["x"]`, `act["y"]` are numeric before `int()` cast; raise `ValueError` on bad types
- [ ] Wire `U2Executor` into `Agent.__init__`: `self._u2_executor = U2Executor(self._u2_pool, loop) if self._u2_pool else None`
- [ ] Add `"u2_batch"` branch in agent dispatch
- [ ] Implement `_handle_u2_batch()` method
- [ ] Return `ok=false, error="unsupported"` for unknown message types from dispatch (protects backward compat)
- [ ] Use blocking `await send_queue.put()` (not `put_nowait`) for control replies
- [ ] Cap `actions` list at 100 items client-side; log WARNING if exceeded

## Edge Cases

- Empty `actions` → return immediately, no session call
- `screenshot` result is large (~200–800 KB base64); document this in API; callers should use sparingly in batches
- `dump_hierarchy` on complex UI can take 3–6 s; runs in executor so loop unblocked
- Session dies mid-batch → current action raises; next `get_session` reconnects; caller sees partial result

## Security Considerations

- `selector["xpath"]` is passed to `dev.xpath()` — uiautomator2 sends it to ATX which evaluates server-side on device; no server-side injection risk since device is trusted
- Batch size cap (100 actions) prevents runaway payloads
