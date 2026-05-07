# Phase 02 — Relay Agent Management UI

**Effort:** 2h  
**Status:** ✅ Completed

## Goal

Add a dedicated **Relay Agents** section (or tab) to the frontend so operators can:
- See all connected relay agents with their device lists
- Trigger bootstrap-all for a relay agent
- See relay agent status (online/offline, last heartbeat)

## Current State

The frontend already has:
- `manage-api.ts` — `listRelayAgents()`, `getRelayAgent()`, `bootstrapAll()`
- `device-list/columns.tsx` — relay badge column in device table
- No dedicated relay agent page/component

## Tasks

### 2.1 Create RelayAgentCard component

✅ **Implemented** — Not strictly needed; RelayAgentsPanel handles card display directly

### 2.2 Create RelayAgentsPanel component

✅ **Implemented** — `front-end/src/features/devices/components/relay-agents-panel/index.tsx` created with polling and agent status display

### 2.3 Wire into existing devices page

✅ **Implemented** — `RelayAgentsPanel` wired into `front-end/src/features/devices/components/device-list/index.tsx`

### 2.4 Bootstrap result toast

✅ **Implemented** — Bootstrap feedback integrated in RelayAgentsPanel

## API Types (already defined)

```ts
interface RelayAgentOut {
  relay_id: string;
  hostname: string;
  ip: string;
  version: string;
  serials: string[];
  status: "online" | "offline";
  connected_at: string | null;
  last_heartbeat_at: string | null;
  disconnected_at: string | null;
}

interface BootstrapAllResult {
  relay_id: string;
  total: number;
  ok: number;
  failed: number;
  results: Array<{ serial: string; ok: boolean; output?: string; error?: string }>;
}
```

## Key Files

| File | Action |
|------|--------|
| `front-end/src/features/devices/components/relay-agent-card/index.tsx` | CREATE |
| `front-end/src/features/devices/components/relay-agents-panel/index.tsx` | CREATE |
| `front-end/src/features/devices/index.tsx` | MODIFY — add panel |
