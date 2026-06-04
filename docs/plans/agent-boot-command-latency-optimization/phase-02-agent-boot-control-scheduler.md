# Phase 2 - Agent-Boot Control Scheduler

Status: Implemented
Priority: P0
Effort: 5h

## Objective

Stop `AgentControlClient` from blocking the gRPC control reader while executing long commands.

## Scope

- Replace inline `await self._handle(ctrl, send_q)` command execution with:
  - fast control reader,
  - per-device scheduler,
  - bounded command workers,
  - async result sender.
- Start with two lanes:
  - `interactive`: short shell/input-like commands.
  - `maintenance`: `bootstrap`, `restart_u2`, `restart_atx`, `restart_scrcpy`.
- Preserve command ordering within a lane for the same serial.

## Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/control_client.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/runtime.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests`

## Design

```text
ControlStream reader
  -> classify command
  -> DeviceCommandScheduler.enqueue(serial, lane, command)
  -> worker executes _agent._execute_command(...)
  -> result queue
  -> producer yields CommandResultMsg
```

## Classification Rules

- `bootstrap`, `restart_u2`, `restart_atx`, `restart_scrcpy`: maintenance.
- `shell`: foreground interactive lane for the same serial, preserving scenario command order.
- Bootstrap/restart commands: maintenance lane so recovery work does not block foreground shell/input commands.

## Safety Rules

- Bound queue length per serial.
- Drop or reject expired commands instead of executing stale interactions.
- Never reorder mutate commands inside one serial/session lane.
- Log queue wait and queue overflow.

## Tests

- A long maintenance command does not prevent a later interactive command from being received/enqueued.
- Same-serial interactive commands preserve order.
- Queue overflow returns an actionable error.
- Control stream shutdown cancels workers cleanly.

## Success Criteria

- `ControlStream` keeps reading while one command executes.
- Interactive command queue wait remains low while maintenance work is pending.
- Existing command result semantics remain compatible with backend.

## Implementation Notes

- Added separate `interactive` and `maintenance` workers inside `AgentControlClient._stream_once`.
- Maintenance commands no longer block the control reader or interactive lane.
- Workers are keyed by `(serial, lane)`, so one device does not block another device's interactive lane.
- Interactive commands still execute sequentially per serial/lane.
- `shell` commands stay in the same per-serial foreground lane, so setup shell commands cannot be overtaken by later taps/input.
- Bootstrap/restart commands use the maintenance lane and no longer block foreground shell/input commands.
- Queue overflow returns an explicit failed `CommandResultMsg` instead of making the backend wait for timeout.
