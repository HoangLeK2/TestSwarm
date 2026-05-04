# Phase 02 - Relay Identity And Security

## Overview

Upgrade `relay_agents` from connection tracking to a production node registry with revocable identity and protocol compatibility.

## Priority

P1. Cloud/local production depends on trusted outbound agents.

## Current State

- `relay_agents` stores `relay_id`, host, IP, version, serials, status.
- gRPC/WS auth uses shared static `RELAY_API_KEY`.
- `agent-boot` persists `.relay_id`.
- `AgentControlClient` sends hardcoded `_AGENT_VERSION = "2.1.0"`.
- `relay.proto` has no protocol version.

## Files

Modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/031_relay_agent_identity.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/relay_agent.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/relay_agents.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/proto/relay.proto`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/agent_control_servicer.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/grpc_relay_server.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/control_client.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/agent.py`

Create tests:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_relay_agent_identity.py`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/tests/test_relay_identity_config.py`

## Schema Additions

Add columns to `relay_agents`:

```sql
site VARCHAR(128) NOT NULL DEFAULT '',
protocol_version INTEGER NOT NULL DEFAULT 1,
token_hash VARCHAR(128),
disabled_at TIMESTAMPTZ,
draining_at TIMESTAMPTZ,
metadata JSONB NOT NULL DEFAULT '{}'
```

Status values:

- `online`
- `offline`
- `draining`
- `disabled`

## Token Model

Short-term:

- Keep shared `RELAY_API_KEY` as compatibility fallback.
- Add per-agent token support:
  - Cloud stores hash.
  - Agent sends `x-relay-id` and `x-relay-token`.
  - Server compares hash.

Long-term:

- mTLS can be added later without changing command contract.

## Protocol Version

Add to `RegisterMsg`:

```proto
int32 protocol_version = 6;
string site = 7;
```

Server behavior:

- Accept protocol v1 in compatibility mode.
- Require v2 once `RELAY_REQUIRE_PROTOCOL_V2=1`.
- Return clear register ack or stream abort for unsupported agents.

## Implementation Steps

1. Add migration 031.
2. Extend ORM/schema/CRUD.
3. Add relay agent token creation/rotation endpoint for admin users.
4. Extend register payload in `agent-boot`.
5. Add server auth path:
   - prefer per-agent token.
   - fallback to shared key only when enabled.
6. Add disabled/draining checks:
   - disabled: reject connection.
   - draining: keep heartbeat but scheduler must not allocate new leases.
7. Update route output to show protocol/site/status.
8. Add compatibility tests.

## Success Criteria

- Each local `agent-boot` can use an independent credential.
- Revoking one node does not require rotating all agents.
- Cloud can reject unsupported protocol versions.
- Existing shared-key agents still work until enforcement flag is enabled.

## Risks

- Generated proto files must be updated in both repos.
- Mitigation: add a single regen command or document exact proto generation command in the phase PR.
