# Phase 01 - Cloud Mode Boundary

## Overview

Make deployment mode explicit. `device_farm` running in cloud must not spawn `agent-boot` as a subprocess. Local development can still keep the convenience path.

## Priority

P1. This prevents the cloud process from assuming local ADB/device access.

## Current State

- `device_farm/main.py` starts `agent-boot` relay unless `FARM_AGENT_BOOT=0`.
- Default relay server points to localhost.
- This is convenient for local dev but unsafe for cloud deployment.

## Files

Modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/main.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/core/env.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/.env.example`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/docs/architecture.md`

Create tests:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_cloud_mode_boundary.py`

## Design

Add deploy mode:

```env
DEVICE_FARM_DEPLOY_MODE=local | cloud
ENABLE_LOCAL_AGENT_BOOT=0 | 1
```

Rules:

- `cloud`: never spawn `agent-boot`, unless `ENABLE_LOCAL_AGENT_BOOT=1` and `DEVICE_FARM_ALLOW_UNSAFE_LOCAL_AGENT=1`.
- `local`: preserve current behavior, but prefer explicit `ENABLE_LOCAL_AGENT_BOOT=1`.
- Default should be safe for production when `DEVICE_FARM_ENV` is `production`, `prod`, or `staging`.

## Implementation Steps

1. Add env helpers:
   - `device_farm_deploy_mode()`
   - `local_agent_boot_enabled()`
   - reuse existing production/staging env convention from DB hardening.
2. Replace `FARM_AGENT_BOOT` default-on behavior.
3. Keep `FARM_AGENT_BOOT` as backward-compatible alias with warning.
4. Update startup logs:
   - cloud mode: "local agent auto-spawn disabled"
   - local mode: "local agent auto-spawn enabled"
5. Update docs and `.env.example`.
6. Add tests for:
   - production/cloud default disables spawn.
   - local explicit enable allows spawn.
   - legacy `FARM_AGENT_BOOT=0` still disables spawn.

## Success Criteria

- Starting `device_farm` in cloud mode cannot spawn local `agent-boot`.
- Local dev still has an explicit opt-in path.
- Tests cover mode matrix.

## Risks

- Existing local dev scripts may rely on default auto-spawn.
- Mitigation: keep `FARM_AGENT_BOOT` compatibility for one release and document new env.
