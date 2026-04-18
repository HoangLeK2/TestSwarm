# agent-boot Stability Rollout Plan

**Status:** Draft
**Created:** 2026-04-18
**Owner:** galari
**Branch:** `refacetor/campaign` → `fix/agent-boot-stability-rollout`
**Target:** Deploy stability fixes from `agent-boot-stability` plan to the production fleet, measure impact, decide on Tier 1 env overrides.
**Related:** `docs/plans/agent-boot-stability/plan.md` (the work being rolled out)

## Goals

1. Commit + deploy all stability fixes **without regressing** existing running fleet.
2. Measure IDR-request effectiveness on Vivo V2352A Android 16 **empirically** before claiming the fix works.
3. Capture 48-hour post-deploy metrics to decide: ship-as-is vs Tier 1 env overrides vs rollback.
4. Leave rollback path obvious — one git revert away.

## Non-Goals

- Tier 1 env overrides (encoder, codec, jar version) — covered separately in Phase 5 as conditional follow-up.
- Tier 2 per-serial encoder memory.
- Tier 3 USB+WiFi hot-failover.
- Refactor of agent-boot build/deploy pipeline.

## Change Inventory (what ships)

Uncommitted changes in `agent-boot/` at time of writing:

| File | Change type | Phase from stability plan |
|------|-------------|---------------------------|
| `pyproject.toml` | deps add (tenacity, aiobreaker, pytest-asyncio<1.0) + pytest config | P0 |
| `uv.lock` | regenerated | P0 |
| `bootstrap.py` | `_ensure_stability_settings()` + wiring AFTER `step_open_app` (fixed bug hôm nay) | P0 |
| `relay/scrcpy_relay.py` | try/finally `_callback_fired`, socket frame-timeout 5s, IDR request on 1.5s stall, TCP keepalive, MallocStackLogging env clean, BaseException guard | P1 + today |
| `relay/session_manager.py` | TTL 300→60s, sweep 30→15s, `stop_all_for_serial` | P1 + P3 |
| `relay/agent.py` | OFFLINE cascade, supervisor wiring, `stop_all_for_serial` call, comment re device_offline not abnormal | P3 + P4 |
| `relay/supervisor.py` | NEW — 15s tick + per-serial aiobreaker around `_restart_with_backoff` | P4 |
| `relay/u2_session_pool.py` | heartbeat 10s w/ identity-checked evict, `.alive` wait_for 3s, `reset_uiautomator()` first | P2 + code-review fix |
| `relay/u2_executor.py` | `_run_with_retry` + narrow dead-session markers | P2 + code-review fix |
| `relay/tests/test_scrcpy_relay_on_fatal.py` | NEW 3 tests for on_fatal semantics | P5 |
| `relay/tests/test_u2_executor.py` | updated error-format assertion | P5 |

53/53 tests green. 2 HIGH code-review issues fixed. `MM` on `bootstrap.py` is staged+unstaged combo, not merge conflict.

## Pre-Flight Checklist (must pass before Phase 1)

1. [ ] `uv run pytest relay/tests/` green (53/53).
2. [ ] `uv run python -c "import ast; ast.parse(open(...))"` green for all changed files.
3. [ ] Git status shows expected file list only — no stray `device_farm/` changes in the stability commits.
4. [ ] Current running agent-boot (PID 30776 on tty s028) has loaded target code (already verified earlier today via file mtime vs process start).
5. [ ] `/proc/net/unix | grep scrcpy` on target device shows server alive — baseline for comparison.

---

## Phase 1 — Empirical Vivo Codec2 IDR verification

**Why:** The IDR-request fix assumes Vivo's `c2.qti.avc.encoder` responds to `signalEndOfInputStream()`. We do not know this is true on Android 16 SDK 36. Without this verification the Phase 4 deploy may ship a no-op on our only test device.

**Effort:** 30 min
**Owner:** galari on laptop with device connected
**Exit criteria:** One data point — IDR frame observed within 500ms after `send_control(bytes([17]))` on a healthy session. OR conclusive evidence it doesn't work.

**Steps:**

1. Verify the fleet still has an active scrcpy session on Vivo V2352A:
   ```bash
   adb -s 10AE7S00HD002JK shell "pgrep -f scrcpy.Server"
   ```
2. Tail logcat filtered for codec events in a dedicated terminal:
   ```bash
   adb -s 10AE7S00HD002JK logcat -c
   adb -s 10AE7S00HD002JK logcat | grep -iE 'scrcpy|codec|keyframe|idr|RESET_VIDEO'
   ```
3. From Python REPL on laptop:
   ```python
   # Attach to running agent process or open fresh socket to the forward:
   import socket
   s = socket.create_connection(("127.0.0.1", 27184))  # control socket (second connect)
   # Skip handshake bytes for existing session — just send RESET_VIDEO:
   s.sendall(bytes([17]))
   ```
   NOTE: this is disruptive — may interrupt the running session. **Run on a quiet window.**
4. Alternative non-disruptive path: `adb -s <sn> shell input keyevent 82` is unrelated; there is no shell equivalent. Must go through the control socket.
5. Observe the logcat output — look for:
   - `MediaCodec` + `keyframe` / `SYNC_FRAME` within ≤500ms → **works**
   - `MediaCodec` error / freeze / nothing → **doesn't work, need Tier 1**
6. Record result in `references/vivo-idr-verification.md` with timestamp + logcat snippet.

**Gate:**
- ✅ IDR received → proceed to Phase 2.
- ❌ No IDR → skip to Phase 5 Tier 1 first, deploy with encoder override enabled from day 1.

---

## Phase 2 — Commit strategy

**Why:** Ship one logical commit (or a small series) so `git revert` is clean. Keep stability-only; strip unrelated `device_farm/` staged changes out of this commit.

**Effort:** 20 min
**Exit criteria:** One commit on `fix/agent-boot-stability-rollout` branch containing ONLY the files listed in "Change Inventory". Existing branch `refacetor/campaign` untouched for now.

**Steps:**

1. Branch:
   ```bash
   cd /Users/hoanglcpila.vn/deviceFarmer
   git checkout -b fix/agent-boot-stability-rollout
   ```
2. Stage only stability files:
   ```bash
   git add agent-boot/pyproject.toml agent-boot/uv.lock agent-boot/bootstrap.py \
           agent-boot/relay/scrcpy_relay.py agent-boot/relay/session_manager.py \
           agent-boot/relay/agent.py agent-boot/relay/supervisor.py \
           agent-boot/relay/u2_session_pool.py agent-boot/relay/u2_executor.py \
           agent-boot/relay/tests/test_scrcpy_relay_on_fatal.py \
           agent-boot/relay/tests/test_u2_executor.py
   # Plus plan docs:
   git add docs/plans/agent-boot-stability/ docs/plans/agent-boot-stability-rollout/
   ```
3. Verify staged diff matches inventory:
   ```bash
   git diff --cached --stat
   ```
4. Commit with HEREDOC message (see appendix A for template).
5. Do NOT push yet — push in Phase 3 only if local canary passes.

**Rollback:** `git checkout refacetor/campaign && git branch -D fix/agent-boot-stability-rollout`.

---

## Phase 3 — Local canary (1 device, 1 hour)

**Why:** Run the new code against one real device before touching the rest of the fleet. Catch obvious runtime regressions that unit tests miss.

**Effort:** 1-1.5 hour (including the 1 hour of observation)
**Exit criteria:** 1 hour continuous operation on Vivo V2352A without:
- Agent thread crashing
- Memory growing >50MB over the hour
- Supervisor breaker opening spuriously
- scrcpy session restarting more than 5× (any more = regression vs current baseline)

**Steps:**

1. Stop current agent: `kill <PID>` (currently 30776).
2. Verify device state:
   ```bash
   adb devices
   adb -s 10AE7S00HD002JK shell settings get global stay_on_while_plugged_in  # should be 7
   ```
3. Run re-bootstrap to apply the fixed `_ensure_stability_settings` (now correctly ordered after step_open_app):
   ```bash
   cd agent-boot
   uv run main.py --bootstrap-only --serial 10AE7S00HD002JK
   ```
4. Start agent with structured log capture:
   ```bash
   uv run main.py 2>&1 | tee /tmp/agent-canary.log
   ```
5. Leave running 1 hour. During this time, do a normal workload: tap/swipe on the device or via the farm UI to exercise u2 + scrcpy.
6. Inject one controlled failure to verify recovery:
   ```bash
   # Kill scrcpy-server on device — should auto-recover within 15s
   adb -s 10AE7S00HD002JK shell pkill -9 -f 'com.genymobile.scrcpy.Server'
   ```
7. Grep log for expected patterns:
   ```bash
   grep -cE 'requested IDR keyframe|encoder stalled|stop_all_for_serial|breaker=open|supervisor tick' /tmp/agent-canary.log
   ```

**Acceptance metrics:**

| Metric | Threshold |
|--------|-----------|
| Agent process alive after 1h | yes |
| `on_fatal callback failed` in log | 0 |
| `encoder stalled` | ≤ 10 |
| `requested IDR keyframe` | >0 if Phase 1 proved IDR works |
| Scrcpy session restarts | ≤ 5 |
| `Task was destroyed but it is pending` (asyncio leak) | 0 |
| Memory growth (ps RSS) | < 50 MB |

**Rollback:** stop agent, `git checkout refacetor/campaign`, restart agent.

---

## Phase 4 — Fleet deploy

**Why:** Once one device passes canary, roll to the rest. Use a staged roll (not big-bang) so a batch-specific regression is caught early.

**Effort:** 2-3 hours (mostly waiting for observation windows)
**Exit criteria:** All production devices running new code, metrics within green thresholds after 48 hours.

**Steps:**

1. Push branch + open PR:
   ```bash
   git push -u origin fix/agent-boot-stability-rollout
   gh pr create --title "fix(agent-boot): stability rollout — P0-P5 + IDR request + MallocStack fix" --body "..."
   ```
2. Merge to `refacetor/campaign` (NOT main — that's a separate release decision).
3. Deploy sequence:
   - **Batch 1 (canary):** 1 device (Vivo V2352A). Already done in Phase 3. Confirm still running healthy.
   - **Batch 2:** 2-3 devices, different models/OEMs. Wait 4 hours.
   - **Batch 3:** remaining fleet. Wait 24 hours.
4. For each batch, restart the agent-boot instance (kill + `uv run main.py`). Preserve device-side state (no reinstall of APKs).
5. Capture baseline metrics BEFORE each batch via:
   ```bash
   # Per-device stop-count in last hour:
   ps -p $AGENT_PID -o etime=  # verify agent up-time
   grep -c 'session stopped' /path/to/log | tail -1
   ```

**Go/no-go at each batch boundary:**

| Signal | Action |
|--------|--------|
| Any batch shows agent crash | Halt. Rollback that batch only. |
| `encoder stalled` rate > 5/hour on any device | Tag device for Tier 1 encoder override, continue rollout |
| `breaker=open` on > 20% of fleet | Halt. Investigate — may be fleet-wide regression |
| All green | Proceed to next batch |

**Rollback (per batch):**
```bash
# On affected host:
kill <agent-pid>
cd /path/to/agent-boot && git checkout refacetor/campaign~1 -- .  # or specific SHA
uv sync  # restore old deps
uv run main.py
```

---

## Phase 5 — Observation window + Tier 1 conditional

**Why:** Data drives the next decision. Either stability fixes alone are enough, or we need per-device encoder overrides.

**Effort:** 48-72 hours observation + up to 2 hours Tier 1 dev if triggered.
**Exit criteria:** Clear ship/iterate decision backed by metrics.

**Metrics to capture (per device, per hour, rolling 48h):**

| Metric | Source | Green | Yellow | Red |
|--------|--------|-------|--------|-----|
| Scrcpy session restarts | log `session stopped` count | ≤ 2/hr | 3-6/hr | > 6/hr |
| `encoder stalled` | log grep | 0/hr | 1-3/hr | > 3/hr |
| `requested IDR keyframe` | log grep | any (means recovery working) | — | 0 when stalled is > 0 (fix no-op) |
| Breaker open events | log `breaker=open` | 0-1/day | 2-4/day | > 4/day |
| u2 heartbeat dead sessions | log `heartbeat evicted` | ≤ 5/day | 6-20/day | > 20/day |
| Agent RSS growth | `ps -o rss=` | < 50MB/day | 50-200MB | > 200MB |
| Manual unplug/replug | ops journal | 0/week | 1-2/week | > 2/week |

**Decision tree at T+48h:**

```
ALL metrics green → ship done. Archive rollout plan, close loop.
MOSTLY green, a few red on one device model → Tier 1 encoder override for that model only.
MANY red across fleet → rollback + Tier 1 as mandatory pre-req → re-rollout.
```

**Tier 1 triggers (condensed from famous-solutions-research.md):**

| Trigger | Tier 1 response |
|---------|-----------------|
| `encoder stalled` on Vivo > 3/hour after IDR recovery exhausted | `SCRCPY_VIDEO_ENCODER=OMX.qcom.video.encoder.avc` for that serial |
| `encoder stalled` on ColorOS 15 device | Try `SCRCPY_JAR_VERSION=2.7` fallback (must verify parser compat first) |
| High-refresh stall (144Hz / 120Hz Vivo) | `SCRCPY_VIDEO_CODEC=h265` for that device |
| Multiple models affected | Add bootstrap `--list-encoders` probe and persist per-model choice |

**Tier 1 dev scope (PRE-BUILT 2026-04-18 — flip via env, no code change needed):**

- [x] `SCRCPY_VIDEO_ENCODER` global + per-serial (`SCRCPY_VIDEO_ENCODER__<serial>`) — forces `video_encoder=<name>` in server_cmd. Empty default = auto-pick.
- [x] `SCRCPY_VIDEO_CODEC` global + per-serial — overrides default `h264` (e.g. `h265`).
- [x] Per-serial env lookup with USB-serial verbatim + TCP-serial safe-char conversion (colons/dots → underscores).
- [x] `bootstrap.py _ensure_stability_settings` logs available encoders per device (dumpsys media.codec parse) so operators know what to flip to.
- [x] 6 unit tests in `relay/tests/test_scrcpy_encoder_override.py` (all pass).
- [ ] `SCRCPY_JAR_VERSION` NOT pre-built — needs v2.7 binary + parser compat verification. Defer until a device actually demands it.

**To activate for a specific device (no restart of other devices needed, but the target device's scrcpy restart picks it up on next session):**

```bash
# Global: force Qualcomm HW H264 on all devices
export SCRCPY_VIDEO_ENCODER=OMX.qcom.video.encoder.avc
# Per-serial: only Vivo V2352A
export SCRCPY_VIDEO_ENCODER__10AE7S00HD002JK=OMX.qcom.video.encoder.avc
# Switch one device to H265
export SCRCPY_VIDEO_CODEC__10AE7S00HD002JK=h265
# Then restart agent-boot; next scrcpy session will use the override.
```

Verify via log line: `[<serial>] scrcpy encoder override: codec=<codec> encoder=<encoder>`

---

## Communication Plan

- **Before Phase 3:** Slack/channel post — "starting agent-boot stability canary on Vivo V2352A for 1h. Farm may see 1 scrcpy restart window ~15s."
- **Before Phase 4 Batch 2:** Slack post — "canary OK. Rolling to 2-3 more devices."
- **Before Phase 4 Batch 3:** Slack post — "batch 2 stable after 4h. Rolling to rest of fleet."
- **At T+48h:** Summary post with metric table.

## Risks & Open Questions

1. **IDR-request is unverified on Vivo Android 16.** Phase 1 addresses directly — if fails, Tier 1 becomes mandatory.
2. **jar v2.7 parser compatibility unknown.** Plan says "verify before using" — binary frame format changed between some scrcpy versions. Dedicate 30 min if Tier 1 triggers jar version fallback.
3. **Fleet size unknown to this planner.** Plan assumes <30 devices; adjust batch sizes if larger.
4. **No Prometheus/structured metrics.** Observation relies on `grep` against text logs. Acceptable for 48h window; formalize if it recurs.
5. **Single test device Vivo V2352A** may not represent fleet. Batch 2 MUST include at least one non-Vivo model.
6. **Process restart mid-scenario-execution** will interrupt any active scenarios. Coordinate with ops on a quiet window.
7. **`refacetor/campaign` branch has many unrelated `device_farm/` staged changes.** Staging step MUST be file-specific — do NOT `git add -A`.

---

## Appendix A — Commit message template

```
fix(agent-boot): stability rollout — retry budgets, IDR recovery, supervisor

Stability work from docs/plans/agent-boot-stability/plan.md + two hot-fixes
from 2026-04-18 (MallocStackLogging env leak, TCP keepalive on scrcpy sockets).

Phases shipped:
- P0: add tenacity + aiobreaker + pytest-asyncio deps
- P1: scrcpy_relay try/finally _callback_fired guard, socket frame-timeout 5s,
       window-based retry 10/120s, MallocStackLogging env strip,
       TCP keepalive (3/3/3 on macOS + Linux), IDR request on 1.5s stall
       (scrcpy PR #5432 client-side implementation — matches upstream RESET_VIDEO)
- P2: u2 session pool heartbeat 10s + identity-checked evict, .alive wait_for 3s,
       reset_uiautomator() first on _reconnect, per-action retry+evict with
       narrow dead-session markers (specific "502 bad gateway" not bare "gateway")
- P3: device-offline cascade — stop_all_for_serial teardown, comment clarifies
       device_offline is non-abnormal (resumes via ONLINE-path)
- P4: RelaySupervisor — 15s tick reconciler, per-serial aiobreaker
       (fail_max=5, timeout=60s) wrapping _restart_with_backoff
- P5: 3 new tests for on_fatal exactly-once semantics

Plus hot-fixes from 2026-04-18 empirical verification:
- bootstrap.py: moved _ensure_stability_settings AFTER step_open_app so the
       STF a11y rebind sequence no longer clears it
- bootstrap.py: removed attempted u2 AccessibilityService whitelist — that
       service does not exist in the APK (u2 uses UiAutomation API)

Tests: 53/53 pass. Code-review HIGH issues (supervisor breaker scope,
on_fatal on KeyboardInterrupt) fixed before commit.

Refs: docs/plans/agent-boot-stability/plan.md
      docs/plans/agent-boot-stability-rollout/plan.md
      docs/plans/agent-boot-stability/references/research-report.md
      docs/plans/agent-boot-stability/references/famous-solutions-research.md
      scrcpy PR #5432 (https://github.com/Genymobile/scrcpy/pull/5432)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Appendix A.1 — Helper tools (pre-built 2026-04-18)

Two small CLI scripts automate the operator work in Phase 1 and Phase 5:

### `tools/verify_idr.py` — Phase 1 empirical IDR check
```bash
cd agent-boot
uv run python tools/verify_idr.py --serial 10AE7S00HD002JK
```
- Pre-flight: verifies device online, scrcpy-server running, adb forward present.
- Sends `RESET_VIDEO` (byte 17) to port 27184.
- Tails `adb logcat` in a thread, watches for `keyframe` / `SYNC_FRAME` / `BUFFER_FLAG_KEY_FRAME`.
- Exit 0 = IDR observed → Tier 1 not needed. Exit 1 = no IDR → flip Tier 1 env.
- **Disruptive:** opens second control socket; may drop live session. Run on quiet window.

### `tools/p5_metrics.py` — Phase 5 rolling metrics snapshot
```bash
# One-shot table
uv run python tools/p5_metrics.py --serial 10AE7S00HD002JK --log /path/to/agent.log

# CSV row for cron'd collection
uv run python tools/p5_metrics.py --serial 10AE7S00HD002JK --log /path/to/agent.log --csv >> /tmp/p5.csv
```
- Reads 7 metrics: agent RSS/threads/uptime, scrcpy PIDs on device, session_restarts, encoder_stalls, idr_requests, breaker_opens, u2_heartbeat_evicts, unplugs.
- Counts log patterns from last ~2MB of the agent log (cheap tail-grep).
- Colors per plan thresholds (🟢 / 🟡 / 🔴).
- Exit 1 if any tracked metric crossed the red line — wire into cron or a `while` loop to page.
- Requires agent stderr redirected to a file (e.g. `uv run main.py 2>&1 | tee /tmp/agent.log`). Without the log file, pattern counts are all zero — agent health metrics still reported.

## Appendix B — Quick-reference commands

**Check current agent state:**
```bash
ps -p $(pgrep -f 'main.py') -o pid,etime,rss
adb devices
adb -s 10AE7S00HD002JK shell 'pgrep -f scrcpy.Server && settings get global stay_on_while_plugged_in'
```

**Tail log for stability events:**
```bash
tail -f /tmp/agent-canary.log | grep -E 'IDR|stalled|breaker|heartbeat|stop_all|on_fatal'
```

**Force scrcpy restart (simulate crash):**
```bash
adb -s 10AE7S00HD002JK shell pkill -9 -f 'com.genymobile.scrcpy.Server'
```

**Rollback one phase:**
```bash
git revert HEAD  # or specific SHA
# redeploy via Phase 4 steps
```
