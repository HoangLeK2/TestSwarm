# Phase 4 — Authorization Gates

Status: Completed

## Overview

Apply relay ownership to every relay read/action route. Device same-LAN filtering remains a secondary visibility filter, not ownership.

## Requirements

- User sees only their relay agents.
- User can operate only their relay agents.
- `bootstrap-all` only affects current user's claimed devices.
- `push-connect-url` can push to a current user's pending device, but cannot target a serial owned by another user.
- Old unowned relays are hidden from normal user APIs.

## Files

- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/relay_agents.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/relay_agent.py`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/relay_agent.py`
- Update `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_relay_agents_routes.py`

## Implementation Steps

1. Add CRUD:
   - `list_relay_agents(db, user_id)`
   - `get_relay_agent(db, relay_id, user_id)`
2. Update routes:
   - `GET /relay-agents`: `user_id=current_user.id`
   - `GET /relay-agents/{relay_id}`: 404 if not owned
   - `POST /relay-agents/{relay_id}/devices/{serial}/register`: require owned relay
   - `POST /relay-agents/{relay_id}/devices/{serial}/push-connect-url`: require owned relay
   - `POST /relay-agents/{relay_id}/bootstrap-all`: require owned relay and user-owned devices
3. Preserve same-LAN filter in `_relay_to_out_same_wifi`.
4. Return 404 for foreign relay ids to avoid existence leaks.
5. Add tests:
   - user B cannot list user A relay.
   - user B cannot register/push/bootstrap via user A relay.
   - owner can register same-LAN unclaimed phone.
   - owner cannot register phone owned by another user.
   - owner cannot bootstrap unclaimed phones.

## Success Criteria

- Cloud can answer: relay owner is `relay_agents.user_id`.
- All relay endpoints enforce owner.
- Existing device ownership checks remain intact.

## Risk Assessment

- Hidden unowned relays may confuse local dev. Mitigate with local-only admin/debug endpoint or clear setup docs.
- Race: two users try to claim same unowned phone. Existing serial uniqueness plus transaction conflict should protect; add explicit conflict test.
