# Phase 4 - Agent-Boot Bootstrap Reliability

Status: Completed
Priority: P1
Effort: 4h

## Overview

Make sure `agent-boot` can reliably provision newly plugged USB phones and WiFi ADB phones when cloud triggers a bootstrap command. This phase verifies the agent side of the 100-phone path.

## Current Behavior To Verify

- `agent-boot/bootstrap.py` default path installs STFService, u2 APKs, atx-agent, permissions, and optional auto-connect.
- Relay command `bootstrap` must call the same complete device setup path or equivalent.
- USB serials can be controlled through USB while `wlan_ip`/`wlan_cidr` are probed for cloud visibility.

## Requirements

- `ctrl.bootstrap(serial)` must install:
  - STFService APK
  - uiautomator2 APKs
  - atx-agent
  - permissions
  - stability settings
- It must work for USB serials and WiFi serials.
- It must not require Wireless Debugging when phone remains USB-connected.
- It should return structured output enough for cloud job result.
- It should not auto-connect to cloud until claim/connect phase, unless explicitly requested.

## Files

- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/adb.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/bootstrap.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/control_client.py`

## Implementation Steps

1. Trace `_execute_command(... CMD_BOOTSTRAP ...)`.
2. Confirm it calls `_bootstrap_device` with all required assets.
3. Align `_bootstrap_device` with `bootstrap.py` if gaps exist.
4. Ensure asset lookup works when `agent-boot` runs from package, Docker, or repo checkout.
5. Add clear result JSON:
   - `stf_installed`
   - `u2_ready`
   - `atx_ready`
   - `permissions_ok`
   - `wlan_ip`
   - `errors`
6. For USB phones:
   - keep serial as USB serial for ADB control,
   - include `wlan_ip`/`wlan_cidr` in capabilities.
7. Do not force `adb tcpip` if the desired flow is USB-control plus cloud connect.

## Success Criteria

- A USB-only ADB phone can be provisioned.
- A WiFi ADB phone can be provisioned.
- A phone with WiFi off is provisioned but marked not cloud-connectable.
- Bootstrap command result is understandable in UI.

## Risks

- Some OEMs block background service permissions. Return actionable error and keep QR/manual fallback.
- USB hub instability with 100 phones. Concurrency limit belongs in backend job runner.

