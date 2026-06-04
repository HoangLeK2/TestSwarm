import type { RelayAgentOut } from '../services/manage-api';

export type RelayConnectionState = 'inactive' | 'connecting' | 'connected';

/** Grace period after (re)connect before showing "connected". */
const CONNECTING_GRACE_MS = 45_000;
/** Heartbeat older than this while still "online" → reconnecting. */
const HEARTBEAT_STALE_MS = 90_000;

export function getRelayConnectionState(
  agent: RelayAgentOut,
  opts?: { busy?: boolean }
): RelayConnectionState {
  if (agent.status !== 'online') return 'inactive';
  if (opts?.busy) return 'connecting';

  const now = Date.now();
  const connectedAt = Date.parse(agent.connected_at);
  if (Number.isFinite(connectedAt) && now - connectedAt < CONNECTING_GRACE_MS) {
    return 'connecting';
  }

  const heartbeatAt = agent.last_heartbeat_at
    ? Date.parse(agent.last_heartbeat_at)
    : NaN;
  if (!Number.isFinite(heartbeatAt) || now - heartbeatAt > HEARTBEAT_STALE_MS) {
    return 'connecting';
  }

  return 'connected';
}

export function isRelayOperational(state: RelayConnectionState) {
  return state === 'connected';
}

function relayLiveConnected(agent: RelayAgentOut): boolean {
  if (typeof agent.live_connected === 'boolean') {
    return agent.live_connected;
  }
  return isRelayOperational(getRelayConnectionState(agent));
}

/** ADB serials visible only while agent-boot is fully connected. */
export function getVisibleRelaySerials(
  agent: RelayAgentOut,
  opts?: { busy?: boolean }
): string[] {
  if (!relayLiveConnected(agent)) {
    return [];
  }
  if (!isRelayOperational(getRelayConnectionState(agent, opts))) {
    return [];
  }
  return agent.serials.filter((s) => s && !s.startsWith('pending-'));
}

export function hasOperationalRelayAgent(agents: RelayAgentOut[]): boolean {
  return agents.some((agent) => relayLiveConnected(agent));
}
