import type { QueryClient } from '@tanstack/react-query';
import type { DeviceOut, FleetStatsOut } from '../services/manage-api';
import { DEVICES_LIST_KEY, FLEET_STATS_KEY } from './device-query-keys';
import {
  lifecycleMessageNeedsRefresh,
  type DeviceLifecycleEventPayload,
  type LifecycleWsMessage
} from './lifecycle-events';
import {
  applyLifecycleMessageToCache,
  type CacheInvalidationTarget
} from './lifecycle-realtime-apply';

export type LifecycleMessageHandlerOptions = {
  onDeviceDead?: (
    event: DeviceLifecycleEventPayload,
    devices: DeviceOut[]
  ) => void;
};

function queryKeyFor(target: CacheInvalidationTarget) {
  return target === 'devices' ? DEVICES_LIST_KEY : FLEET_STATS_KEY;
}

/**
 * Apply a lifecycle WS message to React Query cache.
 * Delegates cache rules to {@link applyLifecycleMessageToCache} for testability.
 */
export function applyLifecycleMessage(
  queryClient: QueryClient,
  msg: LifecycleWsMessage,
  options: LifecycleMessageHandlerOptions = {}
): void {
  if (!lifecycleMessageNeedsRefresh(msg)) return;

  const result = applyLifecycleMessageToCache(
    {
      devices: queryClient.getQueryData<DeviceOut[]>(DEVICES_LIST_KEY),
      fleetStats: queryClient.getQueryData<FleetStatsOut>(FLEET_STATS_KEY)
    },
    msg
  );

  if (result.cache.devices !== undefined) {
    queryClient.setQueryData(DEVICES_LIST_KEY, result.cache.devices);
  }
  if (result.cache.fleetStats !== undefined) {
    queryClient.setQueryData(FLEET_STATS_KEY, result.cache.fleetStats);
  }

  for (const target of result.invalidate) {
    void queryClient.invalidateQueries({ queryKey: queryKeyFor(target) });
  }

  for (const event of result.notifyEvents) {
    options.onDeviceDead?.(event, result.cache.devices ?? []);
  }
}
