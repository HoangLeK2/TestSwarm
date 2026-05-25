# Phase 2 — Enrollment Token API

Status: Completed

## Overview

Expose authenticated user APIs for creating, listing, and revoking agent-boot enrollment tokens. These APIs are how a user proves an `agent-boot` belongs to them.

## Requirements

- Token creation requires authenticated user.
- Raw token is returned once only.
- List endpoint never returns raw token.
- Revoke endpoint is user-scoped.
- Optional name helps users distinguish machines.

## API Contract

```http
POST /api/relay-agents/tokens
Body: { "name": "QA Mac Mini" }
Response: { "id": "...", "token": "dfra_...", "prefix": "dfra_abcd", "name": "QA Mac Mini" }

GET /api/relay-agents/tokens
Response: [{ "id": "...", "prefix": "dfra_abcd", "name": "...", "status": "active", "last_used_at": "..." }]

DELETE /api/relay-agents/tokens/{token_id}
Response: 204
```

## Files

- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/relay_agents.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/relay_agent.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent.py`
- Add tests in `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_relay_agents_routes.py`

## Implementation Steps

1. Add Pydantic schemas:
   - `RelayAgentTokenCreate`
   - `RelayAgentTokenOut`
   - `RelayAgentTokenCreatedOut`
2. Add route handlers before dynamic `/{relay_id}` routes to avoid path capture.
3. Generate tokens as `dfra_` plus at least 32 random bytes encoded urlsafe.
4. Store token hash and short prefix.
5. On revoke, set status `revoked` and `revoked_at`; do not delete immediately.
6. Add tests:
   - user A cannot list/revoke user B token.
   - raw token only present in create response.
   - revoked token cannot be resolved in CRUD.

## Success Criteria

- API token lifecycle is user-scoped.
- No raw token is persisted or logged.
- Existing relay endpoints still work for owned relays after later phases.

## Security Considerations

- Rate-limit token creation if rate limiter is already available.
- Treat raw token as a secret equivalent to `RELAY_API_KEY`.
- Avoid returning token via logs, error messages, or telemetry.
