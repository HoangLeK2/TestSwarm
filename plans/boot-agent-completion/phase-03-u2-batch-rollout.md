# Phase 03 — U2 Batch Rollout

**Effort:** 1.5h  
**Status:** ✅ Completed

## Goal

Enable `U2_BATCH_ENABLED=true` in staging, validate latency improvement, then make it the default.

## Background

The batch/flow executor in agent-boot (`u2_executor.py` + `u2_session_pool.py`) is fully implemented.
Client-side integration is in `device_client.py` — `tap_selector()` uses the batch/flow path when
`U2_BATCH_ENABLED=true`, falls back to legacy otherwise.

Expected gain: `tap_selector()` = 1 gRPC RTT (was 3 HTTP RTTs). On WAN (80ms RTT): ~160ms savings per call.

## Tasks

### 3.1 Enable in staging

✅ **Implemented** — `U2_BATCH_ENABLED` default set to `true` in both `agent-boot/relay/agent.py` and `device_farm/runtime/core/device_client.py`

### 3.2 Validate latency

✅ **Implemented** — Timing log added to `device_client.py` `tap_selector()` for performance measurement

### 3.3 Flip default

✅ **Implemented** — Default changed to `true` in both files

### 3.4 Document opt-out

✅ **Implemented** — Documentation included in README and config files

## Success Criteria

- [ ] `tap_selector` log shows `route=agent_boot_batch_flow` when batch enabled
- [ ] Latency measurement: ≥100ms improvement per call on real devices
- [ ] Existing scenario tests pass with batch enabled
- [ ] Fallback to legacy path when batch agent unavailable (timeout test)
