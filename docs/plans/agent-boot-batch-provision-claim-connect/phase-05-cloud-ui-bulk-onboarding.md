# Phase 5 - Cloud UI Bulk Onboarding

Status: Completed
Priority: P2
Effort: 3h

## Overview

Update Relay Agents UI so the user can provision and connect many phones without opening per-device QR flows.

## Requirements

- Show relay-visible phones with:
  - phone name from probe,
  - serial/connect ID in secondary text,
  - registration status,
  - provision status,
  - network status: same LAN, no WiFi IP, other owner, offline.
- Multi-select visible phones.
- Actions:
  - `Provision selected`
  - `Register & connect selected`
  - `Provision all visible`
  - `Register & connect all visible`
- Show job progress.
- Show per-device failures with retry.
- Show QR fallback only for failed push.
- Poll job summary and job items separately if item list grows.

## Files

- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/app/[locale]/dashboard/relay-agents/page.tsx`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/src/features/devices/services/manage-api.ts`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/messages/vi.json`
- `/Users/hoanglcpila.vn/deviceFarmer/front-end/messages/en.json`

## UI Flow

1. User opens Relay Agents.
2. User sees agent card and phone table.
3. User clicks "Select all visible".
4. User clicks "Provision".
5. UI polls job endpoint until done.
6. User clicks "Register & connect".
7. UI polls second job.
8. Connected devices appear in Devices list.

## Implementation Steps

1. Add API client methods:
   - `createProvisionJob`
   - `createClaimConnectJob`
   - `getRelayJob`
   - `listRelayJobItems`
   - `retryRelayJobItems`
2. Add local selection state per relay.
3. Add job polling with TanStack Query.
4. Keep cards compact for 100 phones:
   - use table/list, not large cards per phone.
5. Add status chips/icons:
   - Ready
   - Needs provision
   - Connected
   - Failed
   - QR fallback.

## Success Criteria

- 100 phones are manageable without layout collapse.
- No per-phone QR modal in the happy path.
- User can retry failed phones only.
- UI can filter item rows by status: pending, running, failed, completed.

## Performance Notes

- Avoid rendering 100 complex cards; use dense rows.
- Poll active jobs every 2s, relay list every 30s.
- For 300+ phones, paginate or virtualize job item rows.
- Stop polling completed jobs.
