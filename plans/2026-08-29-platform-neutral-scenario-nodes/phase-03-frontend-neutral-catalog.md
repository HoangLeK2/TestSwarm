# Phase 03 - Frontend Neutral Catalog

## Goal

Make node catalog neutral by default. Facebook appears as adapter/platform, not as node identity.

## Files To Modify

- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/scenario-steps/types.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/scenario-steps/nested-step-list.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/flow-editor/step-detail-panel.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/flow-editor/platform-select.tsx`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/hooks/use-platform-capabilities.ts`
- `/Users/hoangle/farm/device-farm/front-end/messages/vi.json`
- `/Users/hoangle/farm/device-farm/front-end/messages/en.json`

## UI Rules

- Catalog groups:
  - `Thiet bi`
  - `Nhap lieu`
  - `Kiem tra`
  - `Trich xuat`
  - `Dieu khien luong`
  - `Social`
  - `Legacy`
- Node labels do not include `(FB)` unless node is legacy/migration-only.
- Social node detail panel shows:
  - requested platform
  - supported platforms
  - adapter coverage
  - selected capability
  - platform facets
  - whether execution uses generic recipe or adapter-specific code
- Disabled options show why unsupported.

## Defaulting Rule

- New social node default platform: `auto` or scenario platform, not `facebook`.
- Existing saved node with `platform: facebook` remains unchanged.
- Existing saved node missing platform is shown as `legacy default: facebook` and requires save/migration before new execution policy.

## Trace UI

Show these chips in monitor/detail:

- step id
- path
- node type
- capability
- requested platform
- resolved platform
- adapter
- selected recipe
- platform facets

## Acceptance

- A new user browsing nodes does not see Facebook as the default domain.
- Existing Facebook scenario opens without losing platform values.
- Unsupported platform/capability is visible before execution.
- No frontend request fanout per node.
- UI does not suggest Facebook can substitute for another platform.
