# Phase 1 - Latency Instrumentation

Status: Implemented
Priority: P0
Effort: 3h

## Objective

Add enough timing to prove where command latency is spent before changing scheduling behavior.

## Scope

- Add timestamps to command envelopes where practical:
  - `cloud_enqueue_ts`
  - `agent_received_ts`
  - `queue_start_ts`
  - `exec_start_ts`
  - `exec_done_ts`
  - `result_sent_ts`
  - `cloud_result_ts`
- Log one compact structured line per command id.
- Include serial, command kind, queue/lane, timeout, ok/error, and durations.

## Files

- `/Users/hoangle/farm/device-farm/device_farm/runtime/transports/agent_control_servicer.py`
- `/Users/hoangle/farm/device-farm/device_farm/runtime/transports/adb_relay_server.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/control_client.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`

## Implementation Notes

- Do not change public response contracts in this phase.
- Add trace fields opportunistically to internal JSON/protobuf result handling.
- If protobuf schema changes are too expensive, log timing locally on each side first.
- Use monotonic time for durations; wall time only for logs.

## Tests

- Unit test that command result still resolves by `msg_id`.
- Unit test that added metadata does not break older result consumers.
- Py-compile backend and agent relay files.

## Success Criteria

- A single command can be traced from backend enqueue to agent result.
- Bootstrap/restart and tap/shell-like commands can be compared by queue wait and exec duration.
- No behavior change beyond logs/metadata.

## Implementation Notes

- Added backend-side `ControlConnection.send_command` timing logs for enqueue wait, total wait, timeout, and result status.
- Added agent-side `AgentControlClient._handle_timed` timing logs for queue wait and total command handling time.
- Kept protobuf and public response contracts unchanged.
