import type {
  DeviceOut,
  DeviceStateCountsOut,
  FleetStatsOut
} from '../services/manage-api';
import {
  DEVICE_FSM_STATES,
  normalizeDeviceFsmState,
  type DeviceFsmStateKey
} from './device-fsm';
import type {
  DeviceLifecycleEventPayload,
  LifecycleSnapshotDevice
} from './lifecycle-events';
import {
  deriveSessionOwnerType,
  resolveSessionUserId,
  type SessionOwnerTypeKey
} from './session-owner';

function countKey(state: string | null | undefined): DeviceFsmStateKey {
  return normalizeDeviceFsmState(state);
}

function shiftDeviceCounts(
  counts: DeviceStateCountsOut,
  from: string | null | undefined,
  to: string | null | undefined,
  opts: { remove?: boolean } = {}
): DeviceStateCountsOut | null {
  const next = { ...counts };
  let changed = false;

  if (opts.remove) {
    const fromKey = countKey(from);
    if (next[fromKey] > 0) {
      next[fromKey] -= 1;
      changed = true;
    }
    if (next.total > 0) {
      next.total -= 1;
      changed = true;
    }
    return changed ? next : null;
  }

  if (!to) return null;
  const fromKey = countKey(from);
  const toKey = countKey(to);
  if (fromKey === toKey) return null;

  if (next[fromKey] > 0) {
    next[fromKey] -= 1;
    changed = true;
  }
  next[toKey] += 1;
  return changed ? next : null;
}

function shiftSessionOwnerCounts(
  sessions: FleetStatsOut['active_sessions'],
  ownerKey: SessionOwnerTypeKey,
  delta: 1 | -1
): FleetStatsOut['active_sessions'] | null {
  const next = { ...sessions };
  if (delta === 1) {
    next[ownerKey] += 1;
    next.total += 1;
    return next;
  }
  if (next[ownerKey] <= 0 && next.total <= 0) return null;
  if (next[ownerKey] > 0) next[ownerKey] -= 1;
  if (next.total > 0) next.total -= 1;
  return next;
}

function sessionOwnerDelta(
  event: DeviceLifecycleEventPayload
): SessionOwnerTypeKey | null {
  if (
    event.type !== 'session.claimed' &&
    event.type !== 'session.released' &&
    event.type !== 'device.unpaired'
  ) {
    return null;
  }
  if (event.type === 'device.unpaired' && !event.session_id) return null;
  return deriveSessionOwnerType(
    event.session_id,
    resolveSessionUserId(event.payload)
  );
}

export function applyLifecycleEventToDevices(
  devices: DeviceOut[],
  event: DeviceLifecycleEventPayload
): DeviceOut[] | null {
  if (event.type === 'device.unpaired') {
    const next = devices.filter((d) => d.id !== event.device_id);
    return next.length === devices.length ? null : next;
  }

  if (!event.to_state) return null;

  let changed = false;
  const next = devices.map((d) => {
    if (d.id !== event.device_id) return d;
    if (d.state === event.to_state) return d;
    changed = true;
    return { ...d, state: event.to_state! };
  });
  return changed ? next : null;
}

export function snapshotDeviceIdsMatchCache(
  cached: DeviceOut[],
  snapshotDevices: LifecycleSnapshotDevice[]
): boolean {
  if (cached.length !== snapshotDevices.length) return false;
  const snapshotIds = new Set(snapshotDevices.map((d) => d.device_id));
  return cached.every((d) => snapshotIds.has(d.id));
}

export function applySnapshotToDevices(
  devices: DeviceOut[],
  snapshotDevices: LifecycleSnapshotDevice[]
): DeviceOut[] | null {
  if (!snapshotDevices.length) return null;
  const byId = new Map(snapshotDevices.map((s) => [s.device_id, s.state]));
  let changed = false;
  const next = devices.map((d) => {
    const state = byId.get(d.id);
    if (state === undefined || d.state === state) return d;
    changed = true;
    return { ...d, state };
  });
  return changed ? next : null;
}

export function applyLifecycleEventToFleetStats(
  stats: FleetStatsOut,
  event: DeviceLifecycleEventPayload,
  devices?: DeviceOut[]
): FleetStatsOut | null {
  let skipDeviceShift = false;
  if (devices?.length) {
    const row = devices.find((d) => d.id === event.device_id);
    if (event.type === 'device.unpaired') {
      if (!row) skipDeviceShift = true;
    } else if (
      row &&
      event.from_state &&
      normalizeDeviceFsmState(row.state) !==
        normalizeDeviceFsmState(event.from_state)
    ) {
      skipDeviceShift = true;
    }
  }

  let next = stats;
  let changed = false;

  if (!skipDeviceShift) {
    const deviceShift =
      event.type === 'device.unpaired'
        ? shiftDeviceCounts(stats.devices, event.from_state, null, {
            remove: true
          })
        : shiftDeviceCounts(stats.devices, event.from_state, event.to_state);
    if (deviceShift) {
      next = { ...next, devices: deviceShift };
      changed = true;
    }
  }

  const ownerKey = sessionOwnerDelta(event);
  if (ownerKey) {
    const delta: 1 | -1 = event.type === 'session.claimed' ? 1 : -1;
    const sessionShift = shiftSessionOwnerCounts(
      next.active_sessions,
      ownerKey,
      delta
    );
    if (sessionShift) {
      next = { ...next, active_sessions: sessionShift };
      changed = true;
    }
  }

  return changed ? next : null;
}

export function applySnapshotToFleetStats(
  stats: FleetStatsOut,
  snapshotDevices: LifecycleSnapshotDevice[]
): FleetStatsOut | null {
  if (!snapshotDevices.length) return null;

  const counts: DeviceStateCountsOut = {
    unknown: 0,
    connecting: 0,
    online: 0,
    busy: 0,
    reconnecting: 0,
    dead: 0,
    total: snapshotDevices.length
  };

  for (const row of snapshotDevices) {
    const key = countKey(row.state);
    counts[key] += 1;
  }

  const prev = stats.devices;
  const same =
    prev.total === counts.total &&
    DEVICE_FSM_STATES.every((k) => prev[k] === counts[k]);
  if (same) return null;

  return { ...stats, devices: counts };
}
