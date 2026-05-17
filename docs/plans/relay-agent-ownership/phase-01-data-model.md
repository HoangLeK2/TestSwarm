# Phase 1 — Data Model & Migration

Status: Completed

## Overview

Add persistent ownership and token tracking tables/columns. This phase is database-only plus CRUD support. No runtime behavior changes until later phases.

## Requirements

- Add `relay_agents.user_id` nullable during migration, then populated for newly enrolled agents.
- Add `relay_agent_tokens` table with hashed token storage.
- Keep existing `relay_agents.relay_id` uniqueness.
- Preserve existing deployments where old agents connect without ownership during rollout, but mark them unowned and hide from user APIs in later phases.

## Proposed Schema

Create `relay_agent_tokens`:

```sql
id VARCHAR(36) PRIMARY KEY
user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE
name VARCHAR(255) NOT NULL DEFAULT ''
token_hash VARCHAR(128) NOT NULL UNIQUE
prefix VARCHAR(16) NOT NULL DEFAULT ''
status VARCHAR(16) NOT NULL DEFAULT 'active'
last_used_at TIMESTAMPTZ
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
revoked_at TIMESTAMPTZ
```

Alter `relay_agents`:

```sql
ADD COLUMN user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL;
ADD COLUMN enrollment_token_id VARCHAR(36) REFERENCES relay_agent_tokens(id) ON DELETE SET NULL;
```

## Files

- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/relay_agent.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent.py`
- Create `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/037_relay_agent_ownership.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/__init__.py`

## Implementation Steps

1. Add `RelayAgentToken` model.
2. Add `user_id` and `enrollment_token_id` fields to `RelayAgent`.
3. Add migration `037_relay_agent_ownership.py`; make it idempotent.
4. Add CRUD helpers:
   - `create_relay_agent_token(db, user_id, name) -> raw_token, row`
   - `get_active_relay_token_by_hash(db, token_hash)`
   - `revoke_relay_agent_token(db, token_id, user_id)`
   - `list_relay_agent_tokens(db, user_id)`
   - update `upsert_relay_agent(..., user_id, enrollment_token_id)`
5. Hash tokens with existing secure hashing helper if available; otherwise use SHA-256 with constant-time compare for presented token hash.

## Success Criteria

- Migration runs on fresh and existing DB.
- Existing `relay_agents` rows remain valid with `user_id=NULL`.
- New CRUD unit tests cover create/list/revoke/lookup.

## Risks

- Raw token leakage if logged. Never log full token; show prefix only.
- Unique token collision. Use high-entropy token and unique hash.
