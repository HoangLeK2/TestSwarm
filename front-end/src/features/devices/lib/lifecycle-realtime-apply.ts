import type { DeviceOut, FleetStatsOut } from '../services/manage-api';
import {
  collectLifecycleEvents,
  collectSnapshotReplayEvents,
  lifecycleMessageNeedsRefresh,
  type DeviceLifecycleEventPayload,
  type LifecycleWsMessage
} from './lifecycle-events';
import {
  applyLifecycleEventToDevices,
  applyLifecycleEventToFleetStats,
  applySnapshotToDevices,
  applySnapshotToFleetStats,
  snapshotDeviceIdsMatchCache
} from './lifecycle-cache';

export type DeviceFleetCacheSnapshot = {
  devices: DeviceOut[] | undefined;
  fleetStats: FleetStatsOut | undefined;
};

export type CacheInvalidationTarget = 'devices' | 'fleet-stats';

export type ApplyLifecycleResult = {
  cache: DeviceFleetCacheSnapshot;
  invalidate: CacheInvalidationTarget[];
  /** Events eligible for operator notifications (snapshot replay + live stream). */
  notifyEvents: DeviceLifecycleEventPayload[];
};

function withNotifyEvent(
  result: ApplyLifecycleResult,
  event: DeviceLifecycleEventPayload,
  devices: DeviceOut[]
): ApplyLifecycleResult {
  if (!devices.length) return result;
  return {
    ...result,
    notifyEvents: [...result.notifyEvents, event]
  };
}

/**
 * Pure reducer for lifecycle WS messages — mirrors dashboard cache behaviour.
 */
export function applyLifecycleMessageToCache(
  cache: DeviceFleetCacheSnapshot,
  msg: LifecycleWsMessage
): ApplyLifecycleResult {
  if (!lifecycleMessageNeedsRefresh(msg)) {
    return { cache, invalidate: [], notifyEvents: [] };
  }

  if (msg.type === 'lifecycle.snapshot') {
    const cached = cache.devices;
    if (!cached?.length || !msg.devices.length) {
      return {
        cache,
        invalidate: ['devices', 'fleet-stats'],
        notifyEvents: []
      };
    }
    if (!snapshotDeviceIdsMatchCache(cached, msg.devices)) {
      return {
        cache,
        invalidate: ['devices', 'fleet-stats'],
        notifyEvents: []
      };
    }

    const devices = applySnapshotToDevices(cached, msg.devices) ?? cached;
    const fleetStats = cache.fleetStats
      ? (applySnapshotToFleetStats(cache.fleetStats, msg.devices) ??
        cache.fleetStats)
      : cache.fleetStats;

    let result: ApplyLifecycleResult = {
      cache: { devices, fleetStats },
      invalidate: [],
      notifyEvents: []
    };

    for (const event of collectSnapshotReplayEvents(msg)) {
      result = withNotifyEvent(result, event, devices);
    }
    return result;
  }

  let nextCache = { ...cache };
  let result: ApplyLifecycleResult = {
    cache: nextCache,
    invalidate: [],
    notifyEvents: []
  };

  for (const event of collectLifecycleEvents(msg)) {
    const before = nextCache.devices ?? [];
    result = withNotifyEvent(result, event, before);

    if (nextCache.fleetStats) {
      const patched = applyLifecycleEventToFleetStats(
        nextCache.fleetStats,
        event,
        before
      );
      if (patched) {
        nextCache = { ...nextCache, fleetStats: patched };
      }
    }

    if (nextCache.devices?.length) {
      const patchedDevices = applyLifecycleEventToDevices(
        nextCache.devices,
        event
      );
      if (patchedDevices) {
        nextCache = { ...nextCache, devices: patchedDevices };
      }
    }

    result = { ...result, cache: nextCache };
  }

  return result;
}

/** Apply an ordered stream of lifecycle messages (use-case simulations). */
export function applyLifecycleMessageSequence(
  initial: DeviceFleetCacheSnapshot,
  messages: LifecycleWsMessage[]
): ApplyLifecycleResult {
  return messages.reduce<ApplyLifecycleResult>(
    (acc, msg) => {
      const step = applyLifecycleMessageToCache(acc.cache, msg);
      return {
        cache: step.cache,
        invalidate: [...acc.invalidate, ...step.invalidate],
        notifyEvents: [...acc.notifyEvents, ...step.notifyEvents]
      };
    },
    { cache: initial, invalidate: [], notifyEvents: [] }
  );
}
