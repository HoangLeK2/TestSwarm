# Phase 03 — Named Flow Executor (`u2_flow`)

## Context Links

- Batch executor (primitive ops): `phase-02-batch-executor.md`
- `_resolve()` helper defined in `agent-boot/relay/u2_executor.py`

## Overview

**Priority:** P1  
**Status:** Pending  
**Blocked by:** Phase 02

Execute common high-level UI patterns entirely on agent-boot so that
retries, waits, and multi-step sequences never cross the gRPC boundary.

Each flow is a pure function `(dev, params) -> dict` running in a thread
executor. The flow name maps to a function in `_FLOW_TABLE`.

## Key Insights

- Flows eliminate chatty polling: `find+click+wait` (3 RPCs) → 1 RPC.
- Flows run blocking code; `execute_flow()` offloads via `run_in_executor`.
- All flows share `_resolve()` from phase 02 for selector handling.
- Unknown flow → `ok=false`, no crash.
- Max flow timeout capped at 60 s to avoid hanging gRPC stream.

## Wire Schema

**Request:**
```json
{
  "type":   "u2_flow",
  "id":     "req-456",
  "serial": "192.168.1.10:5555",
  "flow":   "find_click_wait",
  "params": {
    "selector":      {"text": "OK"},
    "click_timeout": 10.0,
    "gone_timeout":  3.0
  }
}
```

**Response:**
```json
{
  "type":  "u2_flow_result",
  "id":    "req-456",
  "flow":  "find_click_wait",
  "ok":    true,
  "value": {"found": true, "clicked": true, "gone": true},
  "error": null
}
```

## Related Code Files

| File | Action | Description |
|------|--------|-------------|
| `agent-boot/relay/u2_executor.py` | MODIFY | Add `execute_flow()` + 5 flow functions + `_FLOW_TABLE` |
| `agent-boot/relay/agent.py` | MODIFY | Add `"u2_flow"` dispatch + `_handle_u2_flow()` |

## Built-in Flows

### 1. `find_click_wait`
Find element, click, wait for it to disappear.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | dict | required | Element selector |
| `click_timeout` | float | 10.0 | Max wait for element to appear (s) |
| `gone_timeout` | float | 3.0 | Max wait for element to disappear after click (s) |

Returns: `{"found": bool, "clicked": bool, "gone": bool}`

```python
def _flow_find_click_wait(dev, p):
    sel   = _resolve(dev, p["selector"])
    found = bool(sel.wait(timeout=min(float(p.get("click_timeout", 10.0)), 60.0)))
    if not found:
        return {"found": False, "clicked": False, "gone": False}
    sel.click()
    gone = bool(sel.wait_gone(timeout=min(float(p.get("gone_timeout", 3.0)), 60.0)))
    return {"found": True, "clicked": True, "gone": gone}
```

### 2. `wait_and_click`
Wait for element to appear, then click.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | dict | required | Element selector |
| `wait_timeout` | float | 10.0 | Max wait time (s) |

Returns: `{"found": bool, "clicked": bool}`

```python
def _flow_wait_and_click(dev, p):
    sel   = _resolve(dev, p["selector"])
    found = bool(sel.wait(timeout=min(float(p.get("wait_timeout", 10.0)), 60.0)))
    if not found:
        return {"found": False, "clicked": False}
    sel.click()
    return {"found": True, "clicked": True}
```

### 3. `find_get_text`
Find element, return its text.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | dict | required | Element selector |
| `timeout` | float | 5.0 | Max wait (s) |

Returns: `{"found": bool, "text": str|null}`

```python
def _flow_find_get_text(dev, p):
    sel = _resolve(dev, p["selector"])
    if not sel.wait(timeout=min(float(p.get("timeout", 5.0)), 60.0)):
        return {"found": False, "text": None}
    return {"found": True, "text": sel.get_text()}
```

### 4. `swipe_until_found`
Swipe in direction until element appears (scroll search).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `selector` | dict | required | Element to search for |
| `direction` | str | `"up"` | `up`/`down`/`left`/`right` |
| `max_swipes` | int | 10 | Abort after this many swipes |
| `step_ratio` | float | 0.6 | Fraction of screen per swipe |

Returns: `{"found": bool, "swipes": int}`

```python
def _flow_swipe_until_found(dev, p):
    direction  = p.get("direction", "up")
    max_swipes = max(0, int(p.get("max_swipes", 10)))
    step_ratio = float(p.get("step_ratio", 0.6))
    w, h       = dev.window_size()
    cx, cy     = w // 2, h // 2
    dy         = int(h * step_ratio / 2)
    dx         = int(w * step_ratio / 2)
    vectors = {
        "up":    (cx, cy + dy, cx, cy - dy),
        "down":  (cx, cy - dy, cx, cy + dy),
        "left":  (cx + dx, cy, cx - dx, cy),
        "right": (cx - dx, cy, cx + dx, cy),
    }
    fx, fy, tx, ty = vectors.get(direction, vectors["up"])
    sel = _resolve(dev, p["selector"])
    for i in range(max_swipes):
        if sel.exists:
            return {"found": True, "swipes": i}
        dev.swipe(fx, fy, tx, ty, duration=0.2)
    return {"found": bool(sel.exists), "swipes": max_swipes}
```

### 5. `input_and_confirm`
Find input field, type text, click confirm button.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `input_selector` | dict | required | Input field selector |
| `text` | str | required | Text to type |
| `confirm_selector` | dict | required | Confirm button selector |
| `wait_timeout` | float | 5.0 | Max wait for each element (s) |

Returns: `{"found_input": bool, "found_confirm": bool, "clicked": bool}`

```python
def _flow_input_and_confirm(dev, p):
    timeout = min(float(p.get("wait_timeout", 5.0)), 60.0)
    inp = _resolve(dev, p["input_selector"])
    if not inp.wait(timeout=timeout):
        return {"found_input": False, "found_confirm": False, "clicked": False}
    inp.set_text(p.get("text", ""))
    btn = _resolve(dev, p["confirm_selector"])
    if not btn.wait(timeout=timeout):
        return {"found_input": True, "found_confirm": False, "clicked": False}
    btn.click()
    return {"found_input": True, "found_confirm": True, "clicked": True}
```

## Flow Table + `execute_flow`

```python
_FLOW_TABLE = {
    "find_click_wait":   _flow_find_click_wait,
    "wait_and_click":    _flow_wait_and_click,
    "find_get_text":     _flow_find_get_text,
    "swipe_until_found": _flow_swipe_until_found,
    "input_and_confirm": _flow_input_and_confirm,
}

class U2Executor:
    # ...existing run_batch...

    async def execute_flow(self, serial: str, flow: str, params: dict) -> dict:
        fn = _FLOW_TABLE.get(flow)
        if fn is None:
            return {"ok": False, "value": None,
                    "error": f"unknown flow: {flow}"}
        try:
            dev = await self._pool.get_session(serial)
        except Exception as exc:
            return {"ok": False, "value": None,
                    "error": f"session unavailable: {exc}"}
        try:
            value = await self._loop.run_in_executor(None, fn, dev, params)
            return {"ok": True, "value": value, "error": None}
        except Exception as exc:
            logger.warning("u2_flow %s failed serial=%s: %s", flow, serial, exc)
            return {"ok": False, "value": None, "error": str(exc)}
```

## Agent Dispatch Hook

```python
# agent-boot/relay/agent.py

elif mtype == "u2_flow":
    asyncio.create_task(self._handle_u2_flow(msg, send_queue))

async def _handle_u2_flow(self, msg: dict, send_queue: asyncio.Queue) -> None:
    if self._u2_executor is None:
        result = {"ok": False, "value": None, "error": "u2 batch not enabled"}
    else:
        result = await self._u2_executor.execute_flow(
            serial = msg.get("serial", ""),
            flow   = msg.get("flow", ""),
            params = msg.get("params") or {},
        )
    result["type"] = "u2_flow_result"
    result["id"]   = msg.get("id", "")
    result["flow"] = msg.get("flow", "")
    await send_queue.put(json.dumps(result).encode())
```

## Todo List

- [ ] Add 5 flow functions to `agent-boot/relay/u2_executor.py`
- [ ] Register in `_FLOW_TABLE`
- [ ] Add `execute_flow()` method to `U2Executor`
- [ ] Cap all timeout params at 60 s: `min(param, 60.0)`
- [ ] Add `"u2_flow"` dispatch branch in `agent.py`
- [ ] Implement `_handle_u2_flow()` method
- [ ] Document each flow's param schema and return shape in module docstring
- [ ] `swipe_until_found`: guard `max_swipes=0` (returns current exists state immediately)

## Edge Cases

- Device rotates mid-flow → uiautomator2 handles coord remapping transparently
- `set_text` on non-editable element → raises; surfaced as `ok=false`
- Flow timeout (60 s) longer than gRPC stream keepalive (30 s) → gRPC pings keep stream alive; no action needed (keepalive already configured in `agent.py`)
- `find_click_wait` clicks but element never disappears → returns `{"gone": false}` — not an error, caller decides

## Security Considerations

Same as phase 02 — no new surface area beyond phase 02 primitive ops.
