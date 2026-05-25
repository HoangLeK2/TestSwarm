# Research Report: agent-boot Stability

**Date:** 2026-04-17
**Scope:** open-source solutions and proven patterns for the three instability issues identified in `plan.md`.
**Methodology:** 4 WebSearch queries (Gemini fallback due to missing auth). Findings cross-referenced against openatx, Genymobile/scrcpy, and asyncio library ecosystem.

---

## Executive Summary

The three stability issues are well-known in the Android-automation ecosystem. Nobody has a magic fix — every serious project wraps `scrcpy`, `adb`, and `uiautomator2` in an external supervisor. Our plan is directionally correct; research sharpens four decisions:

1. **Don't build retry/circuit-breaker from scratch** — adopt `tenacity` + `aiobreaker`. Both are mature, asyncio-native, actively maintained.
2. **`uiautomator2` has `reset_uiautomator()` and `jsonrpc_retry_call` built-in** — use them instead of rolling our own session reset.
3. **Scrcpy has no built-in auto-reconnect by design** (upstream rejected the feature in Genymobile/scrcpy#721) — external wrapper is the only option. Our Phase 1 approach is correct.
4. **Scrcpy-server does NOT restore Android settings on unexpected termination** (Genymobile/scrcpy#5601) — our restart logic must also clean stale server state (kill leftover `app_process`, reset display settings if altered).

---

## Key Findings by Issue

### Issue 1 — scrcpy auto-reconnect

**Upstream stance (Genymobile/scrcpy):**
- Issue #721 "Auto reconnect mode" — requested for years, **not implemented**. Upstream treats reconnect as caller's responsibility. Confirms our external-wrapper approach.
- Issue #6607 — on newer Android, screen lock/unlock triggers ADB disconnect → scrcpy stops immediately.
- Issue #4565 — `WARN: Device disconnected` → `Killing the server` — normal behavior after any socket error.
- Issue #5601 — scrcpy-server does **not** restore Android settings (e.g. show_touches, stay_awake, power mode) if it dies unexpectedly. **Implication:** after a crash we may be left with show_touches=1 or stay_awake=true. Our restart path should tolerate this and reset on clean start.
- Issue #3564 — "Killing the server" is the server's normal self-cleanup path; our relay sees this as socket-EOF.

**Implications for plan:**
- Phase 1 is directionally correct. Add:
  - On every restart, force-kill any leftover `app_process` on device (`adb shell pkill -9 app_process`) — prevents zombie scrcpy-server accumulating.
  - On fresh start, reset Android settings we own (show_touches, stay_awake) to a known state — don't assume prior clean exit.
- No library to replace the hand-rolled loop; scrcpy ecosystem is wrapper-based.

**Sources:**
- [Genymobile/scrcpy#721 — Auto reconnect mode](https://github.com/Genymobile/scrcpy/issues/721)
- [Genymobile/scrcpy#6607 — ADB disconnects, scrcpy stops](https://github.com/genymobile/scrcpy/issues/6607)
- [Genymobile/scrcpy#5601 — server does not restore settings](https://github.com/Genymobile/scrcpy/issues/5601)
- [Genymobile/scrcpy#3564 — Device disconnected, killing server](https://github.com/Genymobile/scrcpy/issues/3564)
- [Genymobile/scrcpy#4565 — WARN after few seconds](https://github.com/Genymobile/scrcpy/issues/4565)

---

### Issue 2 — uiautomator2 / a11y loss

**Library built-ins we should reuse:**
- `uiautomator2.Device.reset_uiautomator()` — already stops+force-stops+restarts the u2d keeper and waits until service is ready. **Replaces our hand-rolled reconnect.**
- `jsonrpc_retry_call` — internal retry wrapper that auto-restarts u2 on gateway errors and read timeouts. **Known issue:** only retries at HTTP layer; won't help if a11y service itself unbinds.

**Common root causes confirmed by issue tracker:**
- #432 "atx-agent recover failed" — persistent, no single fix; most users need `init` re-run.
- #504 — connect fails with "atx-agent recover failed" after device reboot.
- #444 — "atx-agent running but timed out" — network-level: atx-agent alive but uiautomator2 service hung.
- #143 — a11y breaks if the target app has its own AccessibilityService — **device-side fix**: whitelist `com.github.uiautomator` in settings (or via `settings put secure enabled_accessibility_services`).
- Wiki Common-issues — IME issues (FastInputIME), screen-off hangs, ANR on launch.

**Implications for plan:**
- Phase 2 heartbeat: use `device.service("uiautomator").running()` (boolean via atx-agent) as the liveness probe. Wraps the underlying `dumpsys activity services` check. Fast + reliable.
- On dead-session detection, call `device.reset_uiautomator()` **before** falling back to our own reconnect — library reset is battle-tested.
- Add a device-side one-time bootstrap: `settings put secure enabled_accessibility_services com.github.uiautomator/.AccessibilityService` in `adb_device_bootstrap.py`. Prevents target apps from kicking our a11y off.
- FastInputIME: if we type() a lot, ensure FastInputIME is installed and set as current; detect when a test app switches it and restore.

**Sources:**
- [openatx/uiautomator2 source (readthedocs)](https://uiautomator2.readthedocs.io/en/latest/_modules/uiautomator2.html)
- [#432 atx-agent recover failed](https://github.com/openatx/uiautomator2/issues/432)
- [#504 atx-agent recover failed on connect](https://github.com/openatx/uiautomator2/issues/504)
- [#444 atx-agent running but timed out](https://github.com/openatx/uiautomator2/issues/444)
- [#143 AccessibilityService conflict](https://github.com/openatx/uiautomator2/issues/143)
- [Wiki — Common issues](https://github.com/openatx/uiautomator2/wiki/Common-issues)

---

### Issue 3 — General stability (supervisor, retry, circuit-breaker)

**Adopt these libraries (stop rolling our own):**

| Concern | Library | Status | Notes |
|---------|---------|--------|-------|
| Retry with backoff | `tenacity` | Mature, asyncio-native (`@retry`, `AsyncRetrying`) | Handles stop conditions (max_attempts, max_delay), wait strategies (exp, random), retry predicates. Replace hand-rolled loops in `scrcpy_relay.py:304` and a11y path. |
| Circuit-breaker | `aiobreaker` | Active fork of pybreaker, native asyncio | Fail-fast when a device is in a flap loop. Prevents thundering herd on restart. |
| Actor pattern | `rocat` or bespoke | Small, niche | Probably overkill — asyncio.TaskGroup (PY 3.11+) is enough for our size. |
| Proven combo | Tenacity + aiobreaker | Documented pattern | "Robust Redis Client" blog shows the exact pattern: retry inside breaker, breaker opens after N failures in window. |

**Desired-state reconciler (Phase 4 supervisor):**
- Kubernetes-style reconciler is the right frame. Ray's async-actor pattern is overkill for single-host.
- **Recommendation:** plain `asyncio.TaskGroup` + a dict of per-serial `asyncio.Task`. Use `asyncio.Event` for cancel signalling. Don't add new dependencies.
- Precedent: prefect workers and temporal-python workers use this pattern in-house — no library extracted.

**Implications for plan:**
- Phase 1 and Phase 2 retry loops: replace hand-rolled `time.sleep(delay); delay = min(delay*2, max)` with `tenacity.AsyncRetrying(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=30))`. Cleaner, testable.
- Add `aiobreaker.CircuitBreaker(fail_max=5, timeout_duration=timedelta(seconds=60))` per-serial. When opened, skip restart attempts until timeout — prevents our relay from hammering a permanently-offline device.
- Phase 4 supervisor: use `asyncio.TaskGroup` (Python 3.11+). If we're on 3.10, use `aiojobs.Scheduler`.

**Sources:**
- [tenacity — GitHub](https://github.com/jd/tenacity)
- [aiobreaker — GitHub](https://github.com/arlyon/aiobreaker)
- [Robust Redis Client: Async + Tenacity + Circuit Breaker](https://dev.to/akarshan/building-a-robust-redis-client-with-retry-logic-in-python-jeg)
- [Ray async actor pattern](https://docs.ray.io/en/latest/ray-core/patterns/concurrent-operations-async-actor.html)

---

### Bonus — ADB transport (relevant to Phase 3 offline cascade)

**Library choice:**
- `adbutils` (openatx) — pure Python, actively maintained, good fit for direct-TCP to device (bypasses adb-server). Already compatible with our mDNS approach.
- `adb-shell` (Google) — pure Python, lower-level. Good for USB/TLS. We already use it per `farm/adb_transport.py`.
- **Verdict:** keep `adb-shell` for transport, add `adbutils` only if we need high-level helpers we don't have.

**Known failure modes:**
- Screen-lock → TCP keepalive timeout → `device offline`. Mitigation: `settings put global stay_on_while_plugged_in 3`.
- adb-server host crash → all connections disappear at once. Mitigation: we bypass adb-server (direct TCP) so this is already handled.
- Android 11+ pair expiry: once paired via `adb pair`, the key is stored until factory reset. So pair is one-time per device. `adb connect` after reboot **does** work, but the 5555 port may rotate — that's where mDNS `_adb-tls-connect._tcp` matters.
- mDNS caveats: multicast can be filtered by corporate networks. Fallback to stored `ip:port` with reachability probe.

**Implications for plan:**
- Phase 3 offline cascade: on `device offline`, **don't** auto-re-pair — only re-`adb connect` using the stored paired-key. If connect fails repeatedly, emit a `needs_pair` event to farm-server for human intervention.
- Add `stay_on_while_plugged_in=3` to device bootstrap so screen doesn't auto-lock on wired devices.

**Sources:**
- [openatx/adbutils](https://github.com/openatx/adbutils)
- [Android Debug Bridge docs](https://developer.android.com/tools/adb)
- [Punch Through — Wireless Debugging guide](https://punchthrough.com/android-debug-bridge/)

---

## Comparative Analysis — rolled-our-own vs library-adopted

| Component | Current (hand-rolled) | Proposed (library) | Win |
|-----------|----------------------|---------------------|-----|
| scrcpy_relay.py retry loop | `time.sleep(delay); delay*=2` | `tenacity.AsyncRetrying` | Testable, composable, structured logs via listener |
| u2 reconnect on dead session | Manual `kill + reconnect` in pool | `device.reset_uiautomator()` + tenacity | Library-tested edge cases (service ANR, keeper race) |
| Flap protection | None | `aiobreaker.CircuitBreaker` | Stops wasting CPU on permanently-dead devices |
| Supervisor tick | Planned: custom loop | `asyncio.TaskGroup` + dict | Stdlib only, Python 3.11 idiom |
| A11y bootstrap | Assumed user did it | Enforce in `adb_device_bootstrap.py` | Fixes #143 class of bugs at source |

---

## Updated Recommendations for plan.md

Amend the five phases with these specific additions (diff-style):

**Phase 1 — Scrcpy:**
- + Add `pkill -9 app_process` and reset show_touches/stay_awake on every clean start (addr. GH#5601).
- + Replace the hand-rolled retry in `_relay_loop` with `tenacity.Retrying(stop=..., wait=...)`. Keep the 3rd-failure server-restart trigger as a retry callback.

**Phase 2 — U2/A11y:**
- + Use `device.reset_uiautomator()` as the first reconnect path (before manual kill+reconnect).
- + Add device-side bootstrap: enforce `com.github.uiautomator/.AccessibilityService` in `enabled_accessibility_services` at first connect (in `farm/adb_device_bootstrap.py`).
- + Liveness probe = `device.service("uiautomator").running()` — replaces raw `.alive`.
- + Install + pin FastInputIME as default IME during bootstrap; detect IME change on a11y failure and restore.

**Phase 3 — Offline cascade:**
- + Do NOT auto-re-pair on offline. Only re-connect with stored key; escalate `needs_pair` to farm-server after N failures.
- + Bootstrap: `settings put global stay_on_while_plugged_in 3` to prevent screen-lock disconnects (addr. GH#6607).

**Phase 4 — Supervisor:**
- + Wrap restart path with `aiobreaker.CircuitBreaker(fail_max=5, timeout_duration=60s)` per serial. When open, supervisor emits a single log line and skips until breaker closes.
- + Use `asyncio.TaskGroup` (Python 3.11+) to manage per-serial supervisor tasks. If we're stuck on 3.10, use `aiojobs`.

**Phase 5 — Soak:**
- + Add a test fixture that flips the breaker open/closed (mocks 5 consecutive failures) to verify flap-protection.
- + Log schema: use `structlog` if not already — otherwise stdlib `logging` with `extra=` fields.

**New dependencies to add to `pyproject.toml`:**
```toml
tenacity = "^9.0.0"
aiobreaker = "^1.1.0"
# asyncio.TaskGroup is stdlib Python 3.11+
```

---

## Common Pitfalls (collected from issues)

1. **Double-close of futures**: when bridging threads → asyncio with `loop.call_soon_threadsafe()`, guard against calling into a closed loop. Check `loop.is_closed()` first.
2. **Tenacity + asyncio**: use `AsyncRetrying`, NOT `Retrying`. Sync retry inside async will block the event loop.
3. **Circuit-breaker per-serial scope**: do not share a global breaker — one flaky device will trip it and block all others. Dict of breakers keyed by serial.
4. **scrcpy-server leftovers**: always `pkill -9 app_process` before starting a new server. Multiple zombies accumulate and eventually hit the per-UID socket limit.
5. **u2 `.alive` blocking**: wrap in `asyncio.wait_for(..., timeout=3)`. `.alive` can hang on a crashed u2d until TCP keepalive trips (minutes).
6. **Mixing threading.Lock and asyncio.Lock**: pick one per data structure. For the per-serial `_restart_pending` set, use `asyncio.Lock` since it lives in the event-loop thread.

---

## Unresolved Questions

1. Are we on Python 3.10 or 3.11+? `asyncio.TaskGroup` requires 3.11. If 3.10, need `aiojobs` or `asyncio_supervisor`. **Check `pyproject.toml`.**
2. Does `farm/adb_device_bootstrap.py` already run `settings put` commands? If yes, extend. If no, first-time bootstrap flow needs a wrapper.
3. Is FastInputIME acceptable as a default IME for all test workloads, or do some scenarios need the stock IME? (Non-blocking — can be a per-scenario override.)
4. Soak test — do we have a dedicated QA device in CI? If not, Phase 5 soak test is manual-only.

---

## Next Steps

1. Update `plan.md` with the Phase-by-Phase additions above. _(Done: see updated plan.)_
2. Verify Python version in `agent-boot/pyproject.toml`. Pick supervisor library accordingly.
3. Add `tenacity` + `aiobreaker` to `agent-boot/pyproject.toml` before Phase 1 work starts.
4. Extend `farm/adb_device_bootstrap.py` with the three `settings put` commands before Phase 2 work starts.
