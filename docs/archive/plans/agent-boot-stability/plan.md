# agent-boot Stability Plan

**Status:** Implemented 2026-04-17 (code-reviewer HIGH issues fixed; 53/53 tests pass)
**Created:** 2026-04-17
**Owner:** galari
**Branch:** refacetor/campaign
**Target module:** `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/`

## Progress

| Phase | Status | Notes |
|-------|--------|-------|
| 0 Bootstrap prereqs | ✅ | tenacity 9.1.4 + aiobreaker 1.2.0 + pytest-asyncio<1.0 added. `_ensure_stability_settings()` in bootstrap.py: stay_on_while_plugged_in=3, u2 a11y whitelisted |
| 1 Scrcpy recovery | ✅ | try/finally `_callback_fired` guard; socket frame-timeout 5s (env `SCRCPY_FRAME_TIMEOUT_S`); window-based retry 10/120s. KeyboardInterrupt path does NOT fire on_fatal. |
| 2 U2/A11y | ✅ | Heartbeat 10s w/ identity-checked evict; `.alive` wait_for 3s; `_reconnect` tries `device.reset_uiautomator()` first; `_run_with_retry` + specific dead-session markers |
| 3 Offline cascade | ✅ | `stop_all_for_serial` + wired into `_on_device_event` OFFLINE branch |
| 4 Supervisor | ✅ | `relay/supervisor.py` 15s tick; per-serial aiobreaker around `_restart_with_backoff` (fixed from fleet-wide scope per code-review) |
| 5 Observability + tests | ✅ | 3 new tests for on_fatal exactly-once; 53/53 suite green |

### Deferred (noted by code-reviewer, low blast-radius)

- Race between `_on_device_event` ONLINE-path direct `_resume_desired_scrcpy_sessions` and supervisor tick — could double-schedule a restart but `restart_task != done` guard minimizes real-world impact.
- Structured log schema (`event=restart component= serial= …`): not yet uniform across all logger calls; each callsite already logs serial+reason but not in a single JSON-ready format.
- Soak test harness: skipped pending physical device CI.

## Problem Statement

Three instability bugs in the agent-boot relay:

1. **Scrcpy crashes do not auto-reconnect reliably.** Relay thread can exit without emitting `on_fatal`, so the farm-server side never learns and the zombie sweeper only catches it 10s later. Worse: the thread can stream zero frames indefinitely with no timeout.
2. **UIAutomator2 / accessibility control is frequently lost.** The u2 session pool only health-checks at acquire time. A session that dies between `get_session()` and action execution is not detected, and no retry is attempted. ADB-based a11y commands have no per-device reconnect logic either.
3. **General runtime stability is poor.** Device-offline events do not stop scrcpy (only evict u2). No unified supervisor; each component reconnects on its own schedule. No frame timeout on scrcpy stream. No heartbeat on u2.

Reference scout report: see `references/scout-report.md` (condensed findings from the Explore agent, 2026-04-17).

## Goals

- scrcpy auto-recovers from any crash/hang inside ≤15s (p95) without manual intervention.
- u2/a11y command failures due to dead sessions drop to <1% (from current unmeasured).
- Device-offline events cleanly tear down all relay sessions (scrcpy + u2 + ADB) for that serial within 3s.
- Observable: every restart emits a structured log line with serial, component, reason, attempt, backoff.

## Non-Goals

- Reworking the WS protocol between agent-boot and farm-server.
- Changing scrcpy-server itself (Java side under `relay/scrcpy-server/`).
- Replacing uiautomator2 with a different a11y stack.
- Adding Prometheus/OTel metrics (future work — logs only for now).

## High-Level Approach

Three orthogonal fixes, one supervisor layer, then a hardening pass. Do them in phase order because later phases depend on earlier primitives (e.g. phase 4 supervisor consumes the health signals added in phases 1–3).

| Phase | Theme | Blast radius |
|-------|-------|--------------|
| 1 | Scrcpy: guaranteed callback + frame watchdog | `scrcpy_relay.py`, `session_manager.py` |
| 2 | U2/A11y: active heartbeat + per-action retry | `u2_session_pool.py`, `u2_executor.py`, `agent.py` |
| 3 | Device-offline cascade: tear down all components | `agent.py:_on_device_event`, `session_manager.py` |
| 4 | Unified supervisor loop | new `relay/supervisor.py` |
| 5 | Observability + soak test | logs, integration test |

---

## Phase 1 — Scrcpy auto-reconnect guarantee

**Why:** Issue 1. Relay thread can exit silently. 10s zombie grace is too slow. No frame-timeout.

**Files:**
- `agent-boot/relay/scrcpy_relay.py` — relay loop
- `agent-boot/relay/session_manager.py` — zombie sweeper
- `agent-boot/relay/tests/test_scrcpy_relay.py` (new or extend existing)

**Changes:**

1. `scrcpy_relay.py:249–306` (`_relay_loop`): wrap the entire outer `while self._running` in `try/finally`. The `finally` block MUST invoke `self._on_fatal(serial, reason)` if the loop ever exits with `_running=True` and callback not yet fired. Use a boolean `_callback_fired` guard to avoid double-fire.

2. `scrcpy_relay.py:402–479` (`_connect_and_stream` streaming read): replace blocking `recv` with `select.select([sock], [], [], FRAME_TIMEOUT)` where `FRAME_TIMEOUT = 5.0s`. If select returns empty twice consecutively (10s of zero frames) → raise `ScrcpyFrameTimeout` (new exception). The outer loop counts this toward `_reconnect_count` and force-restarts the server on the same 3rd-failure cadence already present at line 299.

3. `session_manager.py:21` (`SESSION_TTL = 300`): lower TTL for active (non-grace) sessions to `SESSION_MAX_STALE = 30s` so the sweeper flags hung streams earlier. Grace period for already-stopping sessions stays at 10s.

4. `scrcpy_relay.py:276–290`: demote the `max reconnects (10)` cap to a *window-based* budget: max 10 failures per 120s window. Outside the window, counter resets. This matches `agent.py:38` `SCRCPY_RESTART_WINDOW_SECONDS=120` so behavior is consistent at both layers.

**Acceptance:**
- Kill scrcpy-server on device via `adb shell pkill -9 app_process` — relay recovers within 15s, emits `runtime_error` → `_on_fatal` → agent-side `_restart_with_backoff` restarts.
- Block frames on device (e.g. `pm disable-user com.android.shell`, or simulate by blocking socket via iptables in test) — FrameTimeout fires within 10s, same recovery path.
- Unit test for `_callback_fired` guard: force `_connect_and_stream` to raise `KeyboardInterrupt` — `on_fatal` still called exactly once.

**Effort:** M (1–2 days)
**Risk:** Medium. Frame-timeout + select rework touches hot path. Must verify no regression in normal streaming throughput (soak test in Phase 5).

---

## Phase 2 — U2/A11y session heartbeat + retry

**Why:** Issue 2. Pool health-check only at acquire. No per-action retry. ADB a11y commands single-shot.

**Files:**
- `agent-boot/relay/u2_session_pool.py`
- `agent-boot/relay/u2_executor.py`
- `agent-boot/relay/agent.py` (a11y worker, ADB helpers)

**Changes:**

1. `u2_session_pool.py`: add heartbeat thread (one per pool, not per session) that wakes every `HEARTBEAT_INTERVAL=10s`. For each idle session in pool, call `device.alive` with a 3s timeout (run in thread-pool executor). If dead → evict + log. If `.alive` blocks ≥3s → kill session (indicates wedged ADB/u2d).

2. `u2_executor.py:213–250`: wrap the `loop.run_in_executor(None, fn, dev, act)` call with a retry loop:
   - Attempt 1: use session from pool.
   - On `uiautomator2.exceptions.*` or `ConnectionError` or timeout → `pool.evict(serial)` and re-acquire.
   - Attempt 2: fresh session.
   - On second failure → return error response with `retryable=true` flag so farm-server can decide.
   - Per-attempt timeout from caller (default 15s).

3. `agent.py:740–822` (`_execute_a11y_action` ADB path): extract ADB-command helper `_a11y_adb_cmd(serial, argv, *, retries=1)`. On `adb: device offline` or exit != 0 with "device" in stderr → trigger `device_watcher` re-evaluation (don't reconnect ADB ourselves — let the watcher-driven state machine do it). Return error; farm-server retries at its level.

4. `u2_session_pool.py:62–66` (`get_session`): before returning a reused session, verify `.alive` with a 1s hard timeout. Replaces current unbounded check.

**Acceptance:**
- Force-kill `atx-agent` on device — heartbeat detects within 10s, next `get_session()` returns a fresh reconnected session.
- Force u2d socket drop mid-action (e.g. `iptables -A OUTPUT -p tcp --dport 9008 -j DROP`) — executor retries on attempt 2, succeeds after unblock, otherwise returns `retryable=true`.
- Unit test: session `.alive` hangs forever — heartbeat kills it, pool size shrinks.

**Effort:** M (1–2 days)
**Risk:** Medium. Heartbeat thread must not leak. u2d `.alive` can block — the timeout wrapper is load-bearing.

---

## Phase 3 — Device-offline cascade

**Why:** Issue 3 core bug. `device_watcher` → `_on_device_event("offline")` today only evicts u2. Scrcpy keeps spinning until its own 10× reconnect cap trips.

**Files:**
- `agent-boot/relay/agent.py:394–452` (`_on_device_event`)
- `agent-boot/relay/session_manager.py` (expose `stop_all_for_serial`)

**Changes:**

1. `session_manager.py`: add `stop_all_for_serial(serial, reason="device_offline")` that iterates all sessions for that serial and calls `stop_session` on each. Must be idempotent.

2. `agent.py:408–409`: on `DeviceState.OFFLINE` event, additionally call `session_manager.stop_all_for_serial(serial, reason="device_offline")`. This runs synchronously (quick — just sets stop flags).

3. `agent.py:_on_session_stopped`: add `"device_offline"` to the *non-abnormal* set so `_restart_with_backoff` does NOT fire on a legit offline. Restart only happens when the device comes back online — via the existing ONLINE → desired-scrcpy resume path at `agent.py:1102–1123`.

4. ADB transport cleanup: no explicit pool, but ensure any open `adb shell` popens for that serial are reaped. Add `_reap_adb_children(serial)` helper (grep existing popens tracked per serial).

**Acceptance:**
- `adb disconnect <ip>:5555` on a connected WiFi device — within 3s all three (scrcpy, u2, adb children) are torn down. Logs show `stop_all_for_serial reason=device_offline`.
- Reconnect device — scrcpy auto-resumes via desired-state path; u2 pool lazily reconnects on next a11y action.
- Regression: plugging/unplugging USB device 10 times in a row does not leak threads (assert via `threading.enumerate()` count in test).

**Effort:** S (0.5–1 day)
**Risk:** Low. Mostly plumbing — the hard part is not double-firing restart on legit offline.

---

## Phase 4 — Unified supervisor

**Why:** Phases 1–3 add component-local recovery. Still missing: top-down sanity loop that notices "desired=streaming, actual=stopped for 60s" and does something.

**Files:**
- `agent-boot/relay/supervisor.py` (new, ~120 lines)
- `agent-boot/relay/agent.py` (start/stop supervisor with agent)

**Changes:**

1. New `Supervisor` task: runs every 15s. For every serial in `DeviceRegistry` with `state=ONLINE` and `desired_scrcpy=True`:
   - If no active scrcpy session AND no pending restart task → schedule `_restart_with_backoff(serial)` with a sticky marker so the loop doesn't re-schedule.
   - If u2 pool shows zero sessions AND last a11y action < 5min ago → prewarm a session.

2. Emits one structured log line per tick: `supervisor tick serials=N healthy=M scrcpy_missing=X u2_missing=Y`.

3. Backpressure: supervisor never does work itself — only schedules via existing primitives. Keeps it debuggable.

**Acceptance:**
- Manually kill a restart task mid-flight (simulate by cancelling its asyncio task). Within 15s, supervisor reschedules it. Serial returns to streaming.
- Supervisor tick log appears every 15s with sensible counts.

**Effort:** M (1–1.5 days)
**Risk:** Medium. Must not double-schedule. Use `asyncio.Event` or a `_restart_pending: set[str]` set guarded by a lock.

---

## Phase 5 — Observability + soak test

**Why:** Verify the first four phases actually achieve the stability targets. No metrics yet — structured logs only.

**Files:**
- `agent-boot/relay/agent.py` — standardize restart/stop log lines
- `agent-boot/relay/tests/test_soak_stability.py` (new)

**Changes:**

1. Unified log schema for all restart/stop events: `event=restart component={scrcpy|u2|adb} serial=<> reason=<> attempt=<> backoff_s=<>`. One emit per event, JSON-serializable dict.

2. Soak test (marked `@pytest.mark.slow`, not in default CI): spawn agent-boot against a real device (use env var `DEVICE_SERIAL`), run for 30 minutes while a background thread injects failures every 60s:
   - `adb shell pkill -9 scrcpy` (randomized)
   - `adb shell am force-stop com.github.uiautomator` (randomized)
   - `adb disconnect` + reconnect cycle
   - Assert: all failures recovered within 30s. No thread leaks. No goroutine-equivalent leaks (thread count stable ±3).

3. Add a lightweight `/health` endpoint on the agent's existing HTTP server (if any) that returns per-serial status. If no such server exists today, skip — logs are enough.

**Acceptance:**
- 30-min soak test passes on one real device without manual intervention.
- All restart events appear in logs with the standard schema — `grep event=restart` in CI shows them grouped correctly.

**Effort:** M (1–2 days, mostly soak harness)
**Risk:** Low — but requires a physical or emulated Android device in the test env.

---

## Rollout

- **Branch:** `fix/agent-boot-stability` off `refacetor/campaign`.
- **Order:** Phases 1 → 2 → 3 → 4 → 5. Each phase shippable independently.
- **Testing gate per phase:** unit tests + 10-minute smoke run against one device.
- **Rollback:** each phase is a separate merge commit; `git revert` per phase if regression.

## Risks & Open Questions

1. **Frame-timeout threshold (5s) may be too aggressive** for slow-rendering devices or low-FPS configs. Make configurable via env var `SCRCPY_FRAME_TIMEOUT_S` (default 5) and watch soak test.
2. **u2d `.alive` may still block past 3s on pathological devices.** If heartbeat kills good sessions, bump timeout to 5s or add a second-chance retry.
3. **Supervisor collision with existing `_resume_desired_scrcpy_sessions`** at `agent.py:1102`. Need to pick ONE source of truth — prefer deleting the existing resume helper once supervisor is proven, to avoid double-scheduling.
4. **No metrics.** If issues recur post-fix, the logs-only approach may not give us aggregate views. Deferred to future work.

## References

- Scout report (2026-04-17): condensed file:line evidence for each issue — in conversation above, will be dropped into `references/scout-report.md` if archived.
- **Research report (2026-04-17):** [`references/research-report.md`](references/research-report.md) — OSS patterns, library comparison, citations from Genymobile/scrcpy, openatx/uiautomator2, openatx/adbutils issue trackers.
- Prior work: observation 417 (Apr 15) noted an auto-restart changeset already landed — but gaps above prove it's incomplete.
- Existing retry primitives: `agent.py:38–41` (window-based budget), `scrcpy_relay.py:304` (exponential backoff), `u2_session_pool.py:129–144` (reaper).

---

## Research-Informed Amendments (2026-04-17)

Research confirmed our direction and added specific library choices + upstream-bug awareness. **Adopt libraries, stop hand-rolling.** Apply these diff-style changes to the phases above.

### New dependencies (add to `agent-boot/pyproject.toml` before Phase 1)

```toml
tenacity  = "^9.0.0"   # retry with exponential backoff, asyncio-native
aiobreaker = "^1.1.0"  # circuit-breaker, active fork of pybreaker
# asyncio.TaskGroup is stdlib Python 3.11+ — verify agent-boot Python version
```

### Phase 1 additions
- `scrcpy-server` does NOT restore Android settings on unexpected termination (Genymobile/scrcpy#5601). **On every clean start**: `pkill -9 app_process` on device first, then reset `show_touches` / `stay_awake` to known state. Prevents zombie-server accumulation hitting per-UID socket limits.
- Replace hand-rolled `time.sleep(delay); delay*=2` at `scrcpy_relay.py:304` with `tenacity.Retrying(stop=stop_after_attempt(10), wait=wait_exponential(min=2, max=30))`. Keep the "every 3rd failure → restart server" logic as a `before_sleep` callback.
- Upstream rejected built-in auto-reconnect (Genymobile/scrcpy#721) — external wrapper is the only supported path. Our approach is correct.

### Phase 2 additions
- **Use the library's built-in reset first.** `uiautomator2.Device.reset_uiautomator()` stops+force-stops+restarts the u2d keeper with battle-tested edge-case handling. Call it before falling back to `pool.evict()` + manual reconnect.
- Liveness probe = `device.service("uiautomator").running()` via atx-agent HTTP, wrapped in `asyncio.wait_for(..., timeout=3)`. More reliable than raw `.alive` which can hang for minutes on crashed u2d.
- **Device-side bootstrap fix for a11y loss root cause (openatx/uiautomator2#143):** when target apps have their own AccessibilityService, Android kicks ours off. Extend `farm/adb_device_bootstrap.py` to enforce:
  ```
  settings put secure enabled_accessibility_services com.github.uiautomator/.AccessibilityService
  settings put secure accessibility_enabled 1
  ```
- IME: install + pin FastInputIME as default during bootstrap. Detect IME switch on a11y failure and restore.

### Phase 3 additions
- Device-side bootstrap: `settings put global stay_on_while_plugged_in 3` — prevents screen-lock → TCP-keepalive-timeout → `device offline` cycle (Genymobile/scrcpy#6607 root cause).
- On `device offline`: do NOT auto-re-pair. Android 11+ paired keys persist until factory-reset, so `adb connect` with stored key is enough. After N connect failures, emit `needs_pair` event to farm-server for human intervention — don't loop forever.

### Phase 4 additions
- Per-serial `aiobreaker.CircuitBreaker(fail_max=5, timeout_duration=timedelta(seconds=60))`. Dict keyed by serial — NEVER share a global breaker (one flaky device would block all others). When open, supervisor emits one log line per tick and skips restart until breaker closes.
- Use `asyncio.TaskGroup` (Python 3.11+). Fallback `aiojobs.Scheduler` if we're on 3.10.
- Proven combo reference: "Robust Redis Client" pattern (retry inside circuit-breaker) — mirror this for every external call (scrcpy start, u2 reconnect, adb connect).

### Phase 5 additions
- Soak test: add a fixture that forces 5 consecutive scrcpy failures to verify the breaker opens, then holds for 60s, then closes.
- Log schema: prefer `structlog` if already present, else stdlib `logging` with `extra=dict(...)`. Standard fields per restart event: `event=restart component={scrcpy|u2|adb} serial=<> reason=<> attempt=<> backoff_s=<> breaker_state={closed|open|half_open}`.

### Bootstrap prerequisites (blocking Phase 1 start)
1. Check Python version in `agent-boot/pyproject.toml`. If 3.10, pin `aiojobs`; if 3.11+, use `TaskGroup`.
2. Extend `farm/adb_device_bootstrap.py` (or equivalent in agent-boot) with the three `settings put` commands.
3. Add tenacity + aiobreaker to `pyproject.toml`, run `uv lock`.

### Common pitfalls (bake into code review checklist)
1. Threading → asyncio bridging: guard `loop.call_soon_threadsafe()` with `loop.is_closed()` check.
2. Use `tenacity.AsyncRetrying` not `Retrying` inside async code — sync retry blocks the event loop.
3. Per-serial breaker dict, not global.
4. Always `pkill -9 app_process` before fresh scrcpy-server start.
5. Wrap `.alive` / `.running()` probes with `asyncio.wait_for(timeout=3)`.
6. Single lock discipline per data structure: `asyncio.Lock` for event-loop-owned data; `threading.Lock` only for cross-thread state.
