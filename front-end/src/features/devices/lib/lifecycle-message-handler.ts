import type { QueryClient } from '@tanstack/react-query';
import type { DeviceOut, FleetStatsOut } from '../services/manage-api';
import { devicesListQueryKey, fleetStatsQueryKey } from './device-query-keys';
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

function organizationIdFromMessage(msg: LifecycleWsMessage): string | null {
  if (msg.type === 'lifecycle.event') {
    return msg.event.organization_id?.trim() || null;
  }
  if (msg.type === 'lifecycle.snapshot' || msg.type === 'lifecycle.batch') {
    return msg.organization_id?.trim() || null;
  }
  return null;
}

function queryKeyFor(target: CacheInvalidationTarget, orgId: string) {
  return target === 'devices'
    ? devicesListQueryKey(orgId)
    : fleetStatsQueryKey(orgId);
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

  const orgId = organizationIdFromMessage(msg);
  if (!orgId) return;

  const devicesKey = devicesListQueryKey(orgId);
  const fleetKey = fleetStatsQueryKey(orgId);
  const devicesCache = queryClient.getQueryData<DeviceOut[]>(devicesKey);
  const fleetStatsCache = queryClient.getQueryData<FleetStatsOut>(fleetKey);

  const result = applyLifecycleMessageToCache(
    {
      devices: devicesCache,
      fleetStats: fleetStatsCache
    },
    msg
  );

  if (result.cache.devices !== undefined) {
    queryClient.setQueryData(devicesKey, result.cache.devices);
  }
  if (result.cache.fleetStats !== undefined) {
    queryClient.setQueryData(fleetKey, result.cache.fleetStats);
  }

  for (const target of result.invalidate) {
    void queryClient.invalidateQueries({
      queryKey: queryKeyFor(target, orgId)
    });
  }

  for (const event of result.notifyEvents) {
    options.onDeviceDead?.(event, result.cache.devices ?? []);
  }
}
