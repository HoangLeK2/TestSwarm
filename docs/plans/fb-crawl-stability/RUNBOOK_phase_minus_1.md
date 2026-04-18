# Runbook — Phase -1 Device-Layer Evidence Pull

> Audience: operator running FB crawl on a physical device that historically flakes.
> Output: `docs/plans/fb-crawl-stability/evidence.md` with a verdict.

---

## Prereqs

- One device that is known to flake on `fb_group_crawl` (ideally the one under serial `49c62ff79ec0c35d` since it already has recent captures).
- Device connected, agent-boot running, device farm API reachable.
- A Facebook account logged in on the device, belonging to a group with ≥ 30 visible posts.

---

## Step 1 — Enable verbose logging

Set env before starting agent-boot:

```bash
export FB_CAPTURE_FAILURES=1            # will light up when Phase 0 ships; no-op today
export AGENT_BOOT_LOG_LEVEL=DEBUG
export DEVICE_FARM_LOG_LEVEL=DEBUG
export LOG_FILE=/tmp/fb-crawl-phase-1.log
```

Restart agent-boot and device-farm:

```bash
cd /Users/hoanglcpila.vn/deviceFarmer
# whatever your start sequence is — docker-compose up, uv run main.py, etc.
```

## Step 2 — Kick the crawl

Via API (or existing UI):

```bash
curl -X POST http://localhost:8080/api/devices/49c62ff79ec0c35d/scenario/run \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d @scenarios/fb_group_crawl.json
```

Or through the front-end scenario preview-stream endpoint if that is how you usually run it.

## Step 3 — While the crawl runs, watch four signals

Tail the log and note timestamps of any of the following:

### A. Scrcpy
```
grep -E "scrcpy.*(on_fatal|frame_timeout|relay_loop|restart)" /tmp/fb-crawl-phase-1.log
```
Expected healthy: no on_fatal, no restart.
Flake signature: on_fatal fired near the missing-post timestamp.

### B. uiautomator2 session
```
grep -E "u2.*(heartbeat|reconnect|reset_uiautomator|alive)" /tmp/fb-crawl-phase-1.log
```
Flake signature: heartbeat_age > 10s right before a missing post, or reconnect mid-run.

### C. a11y service
Start of run + mid-run:
```bash
adb -s 49c62ff79ec0c35d shell settings get secure enabled_accessibility_services
adb -s 49c62ff79ec0c35d shell dumpsys activity service accessibility | head -20
```
Flake signature: service empty / changed mid-run.

### D. ADB reconnect
```
grep -E "(adbd reconnect|device offline|ConnectionRefusedError)" /tmp/fb-crawl-phase-1.log
```
Flake signature: disconnect then reconnect bracketing the flake.

### E. Frame age and force_refresh
```
grep "frame_age" /tmp/fb-crawl-phase-1.log | tail -30
```
Flake signature: `frame_age > 2000ms` on an extract step.

## Step 4 — Identify the flake

Scan DB or UI for the crawl that ran, look for missing posts. For each missing post:
1. Timestamp of the extract step that should have caught it.
2. Cross-reference against signals A-E in that 5-second window.

If no missing-post run happens after 1 hour of tries — the **Quick Wins already shipped today** (wait_stable + locale widen) may have already fixed it. Record that as the verdict.

## Step 5 — Fill out `evidence.md`

Template below. Overwrite `docs/plans/fb-crawl-stability/evidence.md`.

```markdown
# Phase -1 Evidence — YYYY-MM-DD

## Run
- Execution ID:
- Device serial:
- Scenario: fb_group_crawl.json (post-quickwins)
- Account:
- Group: (name)

## Did a flake occur?
- [ ] Yes / [ ] No / [ ] Inconclusive

## If flake:
- Missing post count: N / M visible
- Flake timestamps: [list]
- Signal A (scrcpy): observed / clean
- Signal B (u2): observed / clean
- Signal C (a11y): observed / clean
- Signal D (ADB): observed / clean
- Signal E (frame_age): observed / clean
- XML bundle path: (captures/_failures/... when Phase 0 ships; today: manual `adb uiautomator dump`)

## Verdict (pick one)
- [ ] DEVICE_LAYER — one of A-D fired, flake correlates. Cancel Phases 0-4. Move to agent-boot-stability.
- [ ] PARSER — device clean, XML has posts, parser returned []. Proceed Phase 0 + Phase 2.
- [ ] CAPTURE_TIMING — device clean, frame_age > 2s or XML stale. Proceed Phase 1.
- [ ] SESSION_DEATH — XML is login/rate-limit screen. Proceed F1.8 in Phase 1 (skip Phase 2).
- [ ] QUICK_WINS_FIXED_IT — one hour of runs, no flake reproduced. Monitor in prod; defer Phases 0-4 until next flake report.

## Notes

## Evidence files
- Log: /tmp/fb-crawl-phase-1.log
- Captures:
```

## Step 6 — Commit evidence.md

```bash
git add docs/plans/fb-crawl-stability/evidence.md
git commit -m "phase -1: device-layer evidence for fb-crawl-stability"
```

Then ping the plan owner with the verdict.

---

## Time cap

If Phase -1 takes longer than 1 day elapsed (not effort), stop. Accept the parser hypothesis, proceed with Phase 0 narrow. Record "Phase -1 inconclusive after 1 day" in evidence.md.
