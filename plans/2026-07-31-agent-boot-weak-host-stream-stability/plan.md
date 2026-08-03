---
title: "Agent-boot Stream-first Stability Plan"
description: "Preserve current agent-boot optimizations while adding warm sessions, cached startup, priority scheduling, coordinator actors, and GOP-aware media fast paths for stable 20-40 phone streaming."
status: pending
priority: P1
effort: 24h
issue:
branch: fix/stream-ui
tags: [performance, agent-boot, streaming, adb, infra]
created: 2026-07-31
---

# Agent-boot Stream-first Stability Plan

## Overview

Goal: make `agent-boot` feel close to a dedicated streaming app on weak Windows machines and 20-40 phone farms. Do not blame ADB/hardware by default; optimize how this system consumes ADB/scrcpy/u2 resources and how it keeps visible streams hot.

Core direction:

- Preserve current optimizations; do not rollback to `1.0.2`.
- Keep high-capacity headroom where it helps, but control real pressure via admission and session policy.
- Keep scrcpy sessions warm beyond browser UI lifetime.
- Cache device capability, encoder choice, boot identity, and scrcpy server readiness.
- Use `DeviceActor` as lifecycle/ADB coordinator only; video and active control bytes must stay on fast paths.
- Drop stale H.264 by GOP/keyframe boundary, not by arbitrary delta-frame removal.
- Add hop-level metrics that prove whether delay is ADB, scrcpy startup, media queue, gRPC flow control, backend, or browser decode.

## Current Evidence

- 1.0.2 reportedly feels better than 1.0.3 because newer caps may reduce burst headroom; this is not a reason to rollback optimized code.
- Current code already has ADB admission lanes and per-serial isolation, but visible stream needs stronger resource reservation.
- Customer Windows env still needs a clear high-capacity-but-safe profile.
- `SCRCPY_MAX_SESSIONS=0` means unlimited unless explicitly set.
- Warm scrcpy reuse is the largest immediate user-visible win.
- Media fast path must be GOP-aware because P-frames are not independently decodable.

## Non-goals

- Do not move to WebRTC in this phase.
- Do not rewrite scrcpy unless Phase 5 proves request-IDR requires a server patch.
- Do not remove backend/frontend visible-stream gating.
- Do not route video frames or active scrcpy control bytes through a per-device actor mailbox.
- Do not drop arbitrary H.264 delta frames and continue forwarding dependent P-frames.

## Architecture

`DeviceActor` coordinates state, lifecycle, and ADB work. It is not a byte queue for video/control.

```text
                    DeviceActor
                         │
           manages state/lifecycle/scheduling
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
Control fast path    Video fast path    ADB work queues
scrcpy socket        encoded frames     light / heavy
not ADB             not actor bytes     actor coordinates
```

Target shape:

```text
Browser input
  → Control gateway
  → agent control channel
  → live StreamSession control socket
  → scrcpy-server

scrcpy-server video
  → agent media fast path
  → GOP-aware stale policy
  → gRPC media shard
  → backend media gateway
  → browser decoder

background work
  → DeviceActor
  → ADB light/heavy queues with priority, reservation, coalescing, deadline
```

Resource fences per phone:

```text
DeviceActor
├── lifecycle_lock
│   └── start/stop/recover scrcpy
├── adb_heavy_lock
│   └── push/install/bootstrap/dump-heavy
├── adb_light_semaphore(1-2)
│   └── getprop/pidof/stat/light shell
├── control_fast_path
│   └── active scrcpy control socket, not actor mailbox
└── media_fast_path
    └── video socket drain and media forwarding, not actor mailbox
```

## Target Runtime Shape

### Windows customer default: high headroom, protected execution

```env
RELAY_ADB_POOL_SIZE=48
RELAY_U2_POOL_SIZE=48
RELAY_SCRCPY_POOL_SIZE=16

RELAY_ADB_COMMAND_CONCURRENCY=24
RELAY_ADB_INTERACTIVE_RESERVED=4
RELAY_ADB_HEAVY_CONCURRENCY=4

RELAY_U2_BATCH_CONCURRENCY=12
RELAY_U2_FLOW_CONCURRENCY=12
RELAY_EXTRA_DATA_CONCURRENCY=4
RELAY_CPU_POOL_SIZE=4

SCRCPY_MAX_SESSIONS=8
SCRCPY_DEFAULT_MAX_FPS=12
SCRCPY_DEFAULT_MAX_WIDTH=480
SCRCPY_DEFAULT_BITRATE=600000
RELAY_GRPC_VIDEO_STREAM_SHARDS=4
RELAY_SEND_VIDEO_STALE_MS=200
```

### Weak fallback profile

Keep documented but not default:

```env
RELAY_ADB_COMMAND_CONCURRENCY=12
RELAY_ADB_HEAVY_CONCURRENCY=2
RELAY_U2_BATCH_CONCURRENCY=4
RELAY_U2_FLOW_CONCURRENCY=4
SCRCPY_MAX_SESSIONS=4
SCRCPY_DEFAULT_MAX_FPS=8
SCRCPY_DEFAULT_MAX_WIDTH=420
SCRCPY_DEFAULT_BITRATE=400000
RELAY_GRPC_VIDEO_STREAM_SHARDS=2
```

## Phases

| # | Phase | Status | Effort | Purpose |
|---|-------|--------|--------|---------|
| 1 | Warm scrcpy sessions | Pending | 5h | Reattach fast without restarting scrcpy or touching ADB |
| 2 | Cached startup/bootstrap | Pending | 4h | Avoid redundant probe/push/encoder checks on stream open |
| 3 | Stream-priority reservation | Pending | 5h | Reserve resources for visible stream and control before background work |
| 4 | DeviceActor coordinator | Pending | 6h | Coordinate lifecycle and ADB conflicts without serializing media/control bytes |
| 5 | GOP-aware media fast path and metrics | Pending | 4h | Drop stale video safely and expose hop-level latency |

## Phase 1 — Warm scrcpy sessions

### Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/session_manager.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/scrcpy_relay.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_session_manager.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_scrcpy_desired_lifecycle.py`

### Work

1. Add explicit stream session states:
   - `STOPPED`
   - `STARTING`
   - `VISIBLE`
   - `WARM`
   - `STOPPING`
2. Browser detach must not immediately stop scrcpy:
   - keep scrcpy-server process;
   - keep adb forward/reverse;
   - keep sockets alive;
   - transition `VISIBLE → WARM`.
3. Continue draining video socket in `WARM`.
   - Do not forward full live stream when no viewer.
   - Keep only minimal GOP/cache state for fast reattach.
   - Prevent backpressure from filling gRPC/socket/ADB/MediaCodec.
4. Add adaptive warm TTL:
   - default 120s;
   - recently reused: 180-300s;
   - rarely viewed: 30-60s;
   - resource pressure: LRU evict WARM sessions;
   - never evict VISIBLE sessions.
5. Add warm reuse metrics:
   - `session_warm_reuse_total`
   - `warm_attach_to_first_frame_ms`
   - `warm_evictions_total`
   - `warm_ttl_expired_total`

### Acceptance

- Reopen recently viewed phone without scrcpy restart.
- WARM sessions continue socket drain and do not build stale backlog.
- WARM session eviction only affects non-visible streams.
- Visible session cannot be evicted by LRU.

## Phase 2 — Cached startup/bootstrap

### Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/scrcpy_relay.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/adb.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_remote_adb_server.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_startup_lifecycle.py`

### Work

1. Introduce capability/server cache keyed by:
   - serial;
   - Android `boot_id`;
   - build fingerprint;
   - scrcpy server version;
   - scrcpy server SHA-256.
2. Cache:
   - manufacturer/model/sdk;
   - hardware serial;
   - chosen encoder/codec;
   - scrcpy server ready state;
   - server hash/version.
3. Invalidate on:
   - boot ID change;
   - build fingerprint change;
   - scrcpy version/hash change;
   - encoder start failure;
   - protocol/version error;
   - long offline interval.
4. Do not invalidate on:
   - browser detach;
   - short gRPC reconnect;
   - backend restart;
   - route/page changes.
5. Stream open fast path:
   - if cache valid, start/reuse server immediately;
   - enqueue capability refresh in background only when optional data is stale;
   - block stream open only for data strictly required to start.
6. Encoder fallback:
   - cached hardware encoder;
   - default encoder;
   - known fallback encoder;
   - mark encoder unhealthy and surface reason.

### Acceptance

- Warm/cold stream opens do not repeatedly probe brand/model/hash.
- Valid server cache avoids redundant push/verify.
- Encoder failure invalidates only encoder/server cache, not unrelated state.
- Stream start path has fewer ADB shell calls than current baseline.

## Phase 3 — Stream-priority reservation

### Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/runtime.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/adb_admission.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/u2_session_pool.py`
- `/Users/hoangle/farm/device-farm/agent-boot/deploy/.env.customer.example`
- `/Users/hoangle/farm/device-farm/agent-boot/.env.example`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_adb_admission.py`

### Work

1. Restore high-capacity headroom while keeping admission protection:
   - allow `RELAY_ADB_POOL_SIZE=48`;
   - allow `RELAY_U2_POOL_SIZE=48`;
   - allow `RELAY_SCRCPY_POOL_SIZE=16`;
   - keep real ADB pressure controlled by command/heavy admission.
2. Replace single priority idea with reservation:
   - visible scrcpy lifecycle slots;
   - visible/control slots;
   - background heavy slots;
   - optional per-controller heavy semaphores later if topology is available.
3. Priority classes:
   - P0: visible control via scrcpy control socket, not ADB scheduler;
   - P1: visible video forwarding/media path;
   - P2: scrcpy lifecycle ADB for visible phone;
   - P3: scenario interactive command;
   - P4: uiautomator/dump/probe;
   - P5: push/install/bootstrap/background.
4. Background policy when visible stream exists:
   - background cannot take reserved visible slots;
   - U2 warm can be cancel/pause;
   - capability refresh coalesces;
   - bootstrap/push/install throttles.
5. Add aging to avoid starvation:
   - `effective_priority = base_priority - min(queue_age / aging_interval, max_boost)`.
6. Add Windows balanced profile:
   - high executor pools;
   - bounded command admission;
   - `SCRCPY_MAX_SESSIONS=8`;
   - media shards 4.

### Acceptance

- Visible stream startup/control cannot be stuck behind background push/install.
- Background still progresses under aging.
- Env `48` is accepted as pool headroom, not silently clamped back to 24.
- Heavy maintenance remains bounded.

## Phase 4 — DeviceActor coordinator

### Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/device_state.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/session_manager.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_startup_lifecycle.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_session_manager.py`

### Work

1. Add per-device coordinator abstraction.
2. Actor owns lifecycle and conflicting ADB work only.
3. Actor does not carry:
   - video frame bytes;
   - active scrcpy control messages;
   - media gRPC writes.
4. Command model:
   - priority;
   - created_at;
   - kind;
   - operation_id;
   - coalesce_key;
   - deadline;
   - cancel_on_visible.
5. Coalesce:
   - 10 capability refresh requests → 1;
   - 5 reconnect requests → 1;
   - many U2 warm requests → latest only.
6. Supersede:
   - queued `START_STREAM`;
   - then `STOP_STREAM`;
   - cancel start if not begun.
7. Deadline:
   - visible start: 3s;
   - input: 100-200ms, but normally fast path;
   - background probe: 30s.
8. Recovery fence:
   - allow recovery, health check, stop;
   - defer bootstrap, U2 warm, capability refresh, background install.
9. Add per-serial TCP `adb connect` backoff inside actor/coordinator:
   - 2s, 5s, 10s, 30s max;
   - jitter 0-20%;
   - reset on `device` state.

### Acceptance

- Same phone does not run conflicting lifecycle/heavy ADB operations concurrently.
- Video/control fast paths continue while actor handles background state.
- Duplicate background work coalesces.
- Expired commands are dropped instead of running late.
- TCP reconnect storm is rate limited per serial.

## Phase 5 — GOP-aware media fast path and metrics

### Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/scrcpy_relay.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/runtime.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/grpc_client.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_fair_send_queue.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_grpc_video_packet.py`

### Work

1. Replace arbitrary delta drop assumptions with GOP-aware policy:
   - when stale/backpressured, stop forwarding current GOP;
   - discard until next keyframe;
   - send SPS/PPS/config before restarting;
   - restart forwarding from keyframe.
2. Keep per-session GOP cache:
   - latest codec config;
   - latest keyframe;
   - valid delta chain after that keyframe;
   - max 1 GOP;
   - max 1-2s;
   - max N MB/session.
3. Attach fast path:
   - new viewer receives SPS/PPS;
   - then latest keyframe;
   - then valid delta chain;
   - then live frames.
4. Do not assume stock scrcpy has stable request-IDR API.
   - verify current bundled server/control protocol;
   - if no reliable request-IDR, use discard-until-next-keyframe;
   - optionally configure shorter IDR interval;
   - only patch scrcpy-server if required and version-locked.
5. Add hop timestamps:
   - T0 phone packet PTS;
   - T1 agent received;
   - T2 agent enqueued;
   - T3 gRPC write start/wait;
   - T4 backend received;
   - T5 browser sent;
   - T6 browser received;
   - T7 decoder output;
   - T8 canvas rendered.
6. Add metrics:
   - `scrcpy_start_to_socket_ms`;
   - `scrcpy_start_to_config_ms`;
   - `scrcpy_start_to_keyframe_ms`;
   - `warm_attach_to_first_frame_ms`;
   - `agent_frame_age_ms`;
   - `agent_queue_age_ms`;
   - `grpc_write_wait_ms`;
   - `dropped_stale_frames_total`;
   - `dropped_gops_total`;
   - `idr_wait_ms`;
   - `session_restart_total`;
   - `session_warm_reuse_total`.

### Acceptance

- No forwarding chain like `IDR → P1 → drop P2 → P3`.
- Decoder always resumes from config + keyframe.
- New attach can decode without waiting for arbitrary future config if cache is valid.
- `grpc_write_wait_ms` exposes flow-control stalls.
- Metrics separate agent queue delay from backend/browser delay.

## Verification and release profile

### Focused tests

Run:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-device-farm uv --project agent-boot run pytest \
  agent-boot/relay/tests/test_adb_admission.py \
  agent-boot/relay/tests/test_session_manager.py \
  agent-boot/relay/tests/test_scrcpy_desired_lifecycle.py \
  agent-boot/relay/tests/test_startup_lifecycle.py \
  agent-boot/relay/tests/test_fair_send_queue.py \
  agent-boot/relay/tests/test_grpc_video_packet.py \
  -q
```

### Runtime log criteria

Good log should show:

- `adb_admission.queue_wait_p95_ms` stable, ideally under 50ms during normal interaction.
- `scrcpy.sessions` bounded by customer cap.
- `send_q.video_queue_age_p95_ms` under 50ms for visible streams.
- `send_q.video_handoff_age_p95_ms` under 10ms.
- `scrcpy.worst_device_idr_recovery_p95_ms` under 300ms.
- `warm_attach_to_first_frame_ms` p95 under 300ms.
- `scrcpy_start_to_keyframe_ms` p95 under 3s for cold start.
- `grpc_write_wait_ms` visible and low under normal load.
- `dropped_gops_total` present when stale dropping happens.
- no repeated `auto-reconnected` spam for same serial.
- no `RESOURCE_EXHAUSTED`.

### Release

After focused tests:

1. bump Windows agent-boot Docker version;
2. build Windows-only bundle;
3. include two env profiles in release notes:
   - `windows-balanced-40-phone`
   - `windows-weak-host`

## Rollback Plan

If new version is worse:

1. keep current optimized code; do not rollback to `1.0.2`;
2. lower `RELAY_ADB_COMMAND_CONCURRENCY`;
3. lower `RELAY_ADB_HEAVY_CONCURRENCY`;
4. lower `SCRCPY_MAX_SESSIONS`;
5. shorten WARM TTL if memory/network pressure rises;
6. disable GOP cache before disabling warm sessions;
7. do not revert stream-first scheduling unless logs prove it starves required commands.

## Success Definition

The next Windows test build is acceptable only if:

- it feels at least as stable as 1.0.2;
- visible stream starts faster or equal;
- warm attach p95 under 300ms;
- stream remains stable under 20–40 attached phones;
- unregistered/unused phones do not push/install automatically;
- ADB reconnect does not storm;
- one bad phone does not increase latency of visible phones;
- stale video recovery resumes only from config + keyframe;
- video/control active paths do not go through actor mailbox.
