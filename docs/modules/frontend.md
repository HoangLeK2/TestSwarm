# Frontend

Status: active
Last audited: 2026-05-18

## Scope

The frontend owns dashboard screens, feature-specific hooks/components/services,
generated API client usage, and local Next API proxy adapters.

## Out Of Scope

It does not define backend API truth. Backend route files and OpenAPI generation
are authoritative for API contracts.

## Current Code State

| Area | Source |
|---|---|
| App routes | `front-end/src/app/[locale]/dashboard/*`, `front-end/src/app/[locale]/scenario-flow/[id]/page.tsx` |
| Generated API source | `front-end/generate/openapi.json` |
| Generated client | `front-end/src/features/device-farm/services/generated/DeviceFarmApi.ts` |
| Client bootstrap | `front-end/src/features/device-farm/services/client.ts`, `front-end/src/lib/farm-api.ts` |
| Next API proxies | `front-end/src/app/api/*`, `front-end/src/app/api/_device-farm/proxy.ts` |
| Feature modules | `front-end/src/features/*` |

## Diagrams

### Frontend API Consumption

```mermaid
flowchart LR
    Page[Next app route] --> Feature[Feature component]
    Feature --> Hook[Feature hook]
    Hook --> Service[Feature service]
    Service --> GeneratedClient[Generated DeviceFarmApi client]
    Service --> NextProxy[Next API proxy]
    GeneratedClient --> Backend[/FastAPI backend/]
    NextProxy --> Backend
    Backend --> OpenAPI[OpenAPI schema]
    OpenAPI --> GeneratedClient
```

### Dashboard Feature Map

```mermaid
flowchart TB
    Dashboard[/dashboard/] --> Devices[/devices and device-farm/]
    Dashboard --> Campaigns[/campaigns and scenario-flow/]
    Dashboard --> Accounts[/accounts and account-groups/]
    Dashboard --> DeviceGroups[/device-groups/]
    Dashboard --> Content[/content/]
    Dashboard --> Schedules[/schedules/]
    Dashboard --> Notifications[/notifications/]
    Dashboard --> Analytics[/activity-history/]
    Dashboard --> RelayAgents[/relay-agents/]
```

## Behavior Contract

- Feature folders own UI, hooks, and service adapters for their domain.
- Generated client code is derived from OpenAPI and should not be manually
  edited for durable behavior.
- Next API routes act as proxy/adapters and may not appear in backend OpenAPI.
- Scenario graph UI must remain compatible with backend `ScenarioModel`,
  persisted `nodes`, `edges`, and `steps`.

## Feature Map

| Feature | Routes | Backend modules |
|---|---|---|
| Devices/control | `/dashboard/devices`, `/dashboard/device-farm`, `/dashboard/device-farm/control` | devices, device control, media, sessions |
| Campaigns/scenarios | `/dashboard/campaigns`, `/scenario-flow/{id}`, `/dashboard/scenario-templates` | campaigns, scenario templates, executions |
| Accounts | `/dashboard/accounts`, `/dashboard/device-farm/account-groups` | accounts, account groups |
| Device groups | `/dashboard/device-groups` | device groups |
| Content | `/dashboard/content` | content/extraction |
| Schedules | `/dashboard/schedules` | schedules |
| Notifications | `/dashboard/notifications` | notifications |
| Analytics | `/dashboard/activity-history` | analytics/activity |
| Relay agents | `/dashboard/relay-agents` | relay agents |

## Agent Implementation Checklist

- Prefer feature-local service modules over ad hoc fetch calls in components.
- When backend API changes, regenerate or check OpenAPI and generated client.
- If using a Next API proxy, document whether it is proxy-only or owns frontend
  transformation behavior.
- Keep dashboard navigation aligned with actual feature folders.

## Open Risks

- Some frontend services consume routes that may be backend-only or not present
  in generated client. Treat `docs/api/route-matrix.md` as the parity checklist.
