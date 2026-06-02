# Phase 3 - Bootstrap And Recovery Isolation

Status: Planned
Priority: P0
Effort: 4h

## Objective

Prevent auto-bootstrap and recovery work from causing latency spikes during scenario execution.

## Scope

- Debounce relay online bootstrap by serial.
- Skip bootstrap when u2/atx-agent are already healthy.
- Keep bootstrap/restart in maintenance lane.
- Do not start new maintenance work when interactive work is pending for the same serial, unless explicitly forced.

## Files

- `/Users/hoangle/farm/device-farm/device_farm/web/server.py`
- `/Users/hoangle/farm/device-farm/device_farm/runtime/core/device_client.py`
- `/Users/hoangle/farm/device-farm/device_farm/runtime/transports/agent_control_servicer.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/control_client.py`

## Implementation Notes

- Add a per-serial bootstrap cooldown.
- Add a cheap health probe before bootstrap:
  - atx-agent ping if host is known,
  - u2 session availability when already bound,
  - existing capability heartbeat if fresh.
- Recovery should be idempotent and deduped.
- Existing explicit user-triggered restart/bootstrap should still run, but with clear lane and trace logs.

## Tests

- Relay online event schedules at most one bootstrap per serial per cooldown window.
- Healthy u2/atx skips unnecessary bootstrap.
- Scenario command can run while bootstrap is queued but not yet started.
- Explicit user bootstrap still works.

## Success Criteria

- Reconnect/startup does not create repeated bootstrap storms.
- Maintenance work no longer explains interactive command latency spikes.
