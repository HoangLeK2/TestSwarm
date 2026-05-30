/** Control-plane lifecycle stream payloads (DF-T-02-015). */

export type DeviceLifecycleEventPayload = {
  type: string;
  event_id: string;
  organization_id: string;
  device_id: string;
  from_state: string | null;
  to_state: string | null;
  timestamp: string;
  session_id?: string | null;
  source?: string | null;
  payload?: Record<string, unknown> | null;
};

export type LifecycleSnapshotDevice = {
  device_id: string;
  state: string;
  session_id?: string | null;
  updated_at?: string | null;
};

export type LifecycleWsMessage =
  | {
      type: 'lifecycle.snapshot';
      organization_id: string;
      devices: LifecycleSnapshotDevice[];
      replay: DeviceLifecycleEventPayload[];
    }
  | { type: 'lifecycle.event'; event: DeviceLifecycleEventPayload }
  | {
      type: 'lifecycle.batch';
      organization_id: string;
      events: DeviceLifecycleEventPayload[];
    }
  | { type: 'pong' };

const LIFECYCLE_EVENT_TYPES = new Set([
  'device.state_changed',
  'session.claimed',
  'session.released',
  'device.unpaired'
]);

export function isLifecycleWsMessage(raw: unknown): raw is LifecycleWsMessage {
  if (!raw || typeof raw !== 'object') return false;
  const type = (raw as { type?: unknown }).type;
  return (
    type === 'lifecycle.snapshot' ||
    type === 'lifecycle.event' ||
    type === 'lifecycle.batch' ||
    type === 'pong'
  );
}

/** Collect live lifecycle events to patch cache (snapshot replay is audit-only). */
export function collectLifecycleEvents(
  msg: LifecycleWsMessage
): DeviceLifecycleEventPayload[] {
  if (msg.type === 'lifecycle.event') {
    return LIFECYCLE_EVENT_TYPES.has(msg.event.type) ? [msg.event] : [];
  }
  if (msg.type === 'lifecycle.batch') {
    return msg.events.filter((e) => LIFECYCLE_EVENT_TYPES.has(e.type));
  }
  return [];
}

/** Snapshot replay events — notifications only, never cache patches. */
export function collectSnapshotReplayEvents(
  msg: LifecycleWsMessage
): DeviceLifecycleEventPayload[] {
  if (msg.type !== 'lifecycle.snapshot') return [];
  return msg.replay.filter((e) => LIFECYCLE_EVENT_TYPES.has(e.type));
}

export function lifecycleMessageNeedsRefresh(msg: LifecycleWsMessage): boolean {
  if (msg.type === 'lifecycle.snapshot') {
    return msg.devices.length > 0;
  }
  return collectLifecycleEvents(msg).length > 0;
}
