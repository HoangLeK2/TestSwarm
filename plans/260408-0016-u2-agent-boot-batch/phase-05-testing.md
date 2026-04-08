# Phase 05 — Testing & Validation

## Context Links

- Session pool: `agent-boot/relay/u2_session_pool.py` (from phase 01)
- Executor + flows: `agent-boot/relay/u2_executor.py` (phases 02–03)
- Client adapter: `device_farm/runtime/transports/u2_jsonrpc.py` (phase 04)

## Overview

**Priority:** P2  
**Status:** Pending  
**Blocked by:** Phase 04

Lock in correctness for the session pool, batch executor, and flow executor;
validate latency improvement empirically.

## Related Code Files

| File | Action | Description |
|------|--------|-------------|
| `agent-boot/relay/tests/test_u2_session_pool.py` | CREATE | Session pool unit tests |
| `agent-boot/relay/tests/test_u2_executor.py` | CREATE | Batch executor unit tests |
| `agent-boot/relay/tests/test_u2_flows.py` | CREATE | Flow executor unit tests |
| `agent-boot/scripts/bench_u2_tap_selector.py` | CREATE | Latency benchmark (not installed) |

## Unit Tests

### `test_u2_session_pool.py`

Mock `uiautomator2.connect` via injected `connect_fn`:

```python
import pytest, asyncio, time
from unittest.mock import MagicMock
from relay.u2_session_pool import U2SessionPool, SESSION_TTL_SECONDS

@pytest.fixture
def mock_device():
    dev = MagicMock()
    dev.alive = True
    return dev

@pytest.fixture
def pool(event_loop, mock_device):
    fn = MagicMock(return_value=mock_device)
    p = U2SessionPool(loop=event_loop, connect_fn=fn)
    return p, fn, mock_device
```

Tests:

- [ ] `test_get_session_connects_once` — two sequential calls yield same device; `connect_fn` called once
- [ ] `test_concurrent_get_session_safe` — two concurrent calls race; `connect_fn` called once (not twice)
- [ ] `test_evict_removes_entry` — `evict()` removes entry; next call re-connects
- [ ] `test_evict_closes_device` — `evict()` calls `device.stop()`
- [ ] `test_reap_loop_evicts_idle` — monkey-patch `time.monotonic` to advance past `SESSION_TTL_SECONDS`; reaper evicts
- [ ] `test_dead_session_reconnects` — set `device.alive = False`; next `get_session` reconnects (calls `connect_fn` again)
- [ ] `test_connect_timeout_raises` — `connect_fn` hangs; `asyncio.wait_for` raises; entry not cached
- [ ] `test_usb_serial_no_colon` — serial `"emulator-5554"` passes `serial` directly to `connect_fn`

### `test_u2_executor.py`

Inject fake pool returning a `MagicMock` device:

```python
@pytest.fixture
def executor(event_loop, mock_device):
    pool = AsyncMock()
    pool.get_session.return_value = mock_device
    return U2Executor(pool=pool, loop=event_loop), mock_device
```

Tests:

- [ ] `test_run_batch_success` — `[click, exists, get_text]`; mock returns values in order; aggregated results correct
- [ ] `test_run_batch_empty` — empty list → `ok=true, results=[]`; no pool call
- [ ] `test_run_batch_early_exit` — second op raises; third not called; `stopped_at=1`
- [ ] `test_run_batch_no_early_exit` — `early_exit=false`; all ops run; failures captured individually
- [ ] `test_unknown_op_fails_cleanly` — op `"foo"` → `ok=false, error=...`; dispatcher survives
- [ ] `test_session_unavailable` — `pool.get_session` raises → `ok=false, stopped_at=0`
- [ ] `test_selector_xpath_dispatch` — `{"xpath":"//View"}` → `dev.xpath("//View")` called
- [ ] `test_selector_kwargs_dispatch` — `{"text":"OK"}` → `dev(text="OK")` called
- [ ] `test_screenshot_returns_base64` — mock device returns bytes; result is valid base64

### `test_u2_flows.py`

```python
@pytest.fixture
def executor_with_device(event_loop):
    pool = AsyncMock()
    dev  = MagicMock()
    pool.get_session.return_value = dev
    exc  = U2Executor(pool=pool, loop=event_loop)
    return exc, dev
```

Tests:

- [ ] `test_find_click_wait_happy` — `sel.wait=True`, `sel.wait_gone=True` → `{found,clicked,gone}` all true
- [ ] `test_find_click_wait_not_found` — `sel.wait=False` → short-circuits, click never called
- [ ] `test_find_click_wait_clicked_not_gone` — wait=True, wait_gone=False → `{found:T, clicked:T, gone:F}`
- [ ] `test_wait_and_click_found` — wait=True → click called, returns `{found:T, clicked:T}`
- [ ] `test_wait_and_click_not_found` — wait=False → click not called
- [ ] `test_find_get_text_found` — returns `{"found":T, "text":"hello"}`
- [ ] `test_find_get_text_not_found` — returns `{"found":F, "text":null}`
- [ ] `test_swipe_until_found_on_third` — `exists` False × 2, then True; returns `{"found":T, "swipes":2}`
- [ ] `test_swipe_until_found_exhausts` — never found; returns `{"found":F, "swipes":max_swipes}`
- [ ] `test_swipe_until_found_zero_swipes` — `max_swipes=0` → returns current `exists` immediately
- [ ] `test_input_and_confirm_success` — all elements found; `set_text` + `click` called
- [ ] `test_input_and_confirm_no_input` — input wait fails → returns `{found_input:F, ...}`
- [ ] `test_input_and_confirm_no_confirm` — input found but confirm wait fails
- [ ] `test_unknown_flow_returns_error` — `flow="nonexistent"` → `ok=false` with message

## Latency Benchmark

Create `agent-boot/scripts/bench_u2_tap_selector.py` (not part of the installed package):

```python
"""
Usage: python bench_u2_tap_selector.py --serial 192.168.1.10:5555 --runs 50

Runs tap_selector(text="OK") via legacy u2_request path and new u2_flow path,
prints latency comparison table.
"""
```

- Warm-up: 5 iterations before recording
- Measure p50, p90, p99 for each path
- Print side-by-side table with delta and improvement %

**Acceptance threshold:** p50 flow ≤ 40% of p50 legacy on a ≥50 ms-RTT link.

## Manual Validation Checklist

- [ ] Start agent-boot with `U2_BATCH_ENABLED=true`; start device_farm
- [ ] Click a button via dashboard → confirm `u2_flow find_click_wait` appears in agent-boot logs
- [ ] Set `U2_BATCH_ENABLED=false`; confirm `u2_request` logs reappear (legacy path)
- [ ] Disconnect device mid-session; reconnect; confirm pool evicts + re-establishes without restarting agent-boot
- [ ] Run `tasks/example_task.py` with batch enabled — verify no regressions
- [ ] 30-minute idle: monitor memory for session pool (expect O(n_devices) entries, no growth)
- [ ] Run benchmark script; confirm ≥40% p50 improvement

## Regression Guard

- [ ] Add one test that calls the legacy `u2_http()` path via `_RelaySession` end-to-end and asserts unchanged behavior — protects the `_request_reply` refactor

## Exit Criteria

- [ ] All unit tests green (`pytest agent-boot/relay/tests/ -v`)
- [ ] No regressions in existing agent-boot test suite
- [ ] Latency benchmark meets ≥40% p50 reduction threshold
- [ ] Manual validation checklist complete
- [ ] Feature flag documented in `config.yaml` + agent-boot `README.md`
