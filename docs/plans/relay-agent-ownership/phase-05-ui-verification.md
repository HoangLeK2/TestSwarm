# Phase 5 — UI & Verification

Status: Completed

## Overview

Expose relay enrollment in the dashboard and document the new setup flow. Verify security, ownership, and device discovery behavior end-to-end.

## UX Flow

1. User opens Relay Agents page.
2. User clicks "Create token".
3. UI shows token once with copy button.
4. User puts token into `agent-boot/.env`:

```env
RELAY_ENROLLMENT_TOKEN=dfra_...
```

5. User starts `agent-boot`.
6. Cloud shows only that user's relay.
7. Relay card shows hostname, LAN IP, online status, and same-LAN phones.

## Files

- Modify `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/services/manage-api.ts`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/components/relay-agents-panel.tsx`
- Create or modify token management component under `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/components/`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/README.md`
- Modify `/Users/hoanglcpila.vn/deviceFarmer/.env.example`

## Implementation Steps

1. Add API client methods:
   - `createRelayToken`
   - `listRelayTokens`
   - `revokeRelayToken`
2. Add UI section for enrollment tokens.
3. Show raw token only after create; warn it cannot be shown again.
4. Add revoke action.
5. Update relay card to show owner-derived status:
   - owned by current user by definition
   - show token prefix/name if API exposes it
6. Update docs:
   - cloud setup
   - local dev setup
   - token rotation
   - what "same WiFi/LAN" means.
7. Verify with two users:
   - User A creates token and runs agent.
   - User B cannot see relay.
   - User B cannot operate serials from that relay.
   - User A can see same-LAN phones and claim unowned phone.

## Validation Commands

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run pytest tests/test_relay_agents_routes.py tests/test_auth_security.py

cd /Users/hoanglcpila.vn/deviceFarmer/front-end
pnpm exec tsc --noEmit
pnpm exec eslint 'src/app/[locale]/dashboard/relay-agents/page.tsx' src/features/devices/services/manage-api.ts --max-warnings=0
```

## Success Criteria

- User can self-serve relay enrollment.
- User can revoke a relay token.
- Agent ownership is visible and auditable.
- Multi-user isolation is test-covered.
