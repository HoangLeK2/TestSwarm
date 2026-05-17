# Phase 3 — Agent-Boot Identity Handshake

Status: Completed

## Overview

Make `agent-boot` send a user enrollment token during control-channel register. Server resolves the token into `user_id` and persists relay ownership.

## Requirements

- Support environment variable `RELAY_ENROLLMENT_TOKEN`.
- Do not put token in normal logs.
- Server rejects missing/invalid token in strict multi-user mode.
- Transitional mode may allow unowned relay for local dev only.

## Wire Contract

Current control register sends:

```python
RegisterMsg(relay_id, serials, hostname, ip, agent_version)
```

Implemented minimal change:

- Agent reads `RELAY_ENROLLMENT_TOKEN` from env/CLI.
- Agent sends token as gRPC metadata header `x-relay-enrollment-token`.
- Server reads invocation metadata before ACK.

This avoids unnecessary generated-stub churn while keeping the register protobuf
wire contract compatible.

## Files

- Modify `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/control_client.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/main.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/agent_control_servicer.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/web/server.py`

## Implementation Steps

1. Add `RELAY_ENROLLMENT_TOKEN` CLI/env handling in `agent-boot`.
2. Add token to control register payload.
3. In server control servicer:
   - Hash presented token.
   - Resolve active token row.
   - If invalid, close stream with auth error.
   - Pass `user_id` and `enrollment_token_id` to persistence callback.
4. Update `_on_ctrl_register` callback to persist ownership.
5. Update heartbeat callback to update only matching owned relay by `relay_id`.
6. Add clear server logs:
   - relay id
   - user id
   - token prefix
   - never full token.

## Success Criteria

- New relay agent row has `user_id`.
- Reconnecting same relay preserves owner.
- Invalid/revoked token cannot register.
- Old unowned relay cannot appear in user API in Phase 4.

## Rollout Note

Keep a config flag:

```env
RELAY_AGENT_OWNERSHIP_REQUIRED=true
```

Default true in cloud/staging/prod. Local dev may keep false briefly.
