'use client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient
} from '@tanstack/react-query';
import {
  devicesApi,
  type DeviceCreate,
  type DeviceListParams,
  type DeviceOut
} from '../services/manage-api';
import {
  DEVICES_LIST_KEY,
  FLEET_STATS_KEY,
  devicesListQueryKey,
  fleetStatsQueryKey
} from '../lib/device-query-keys';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  LIFECYCLE_WS_LIVE_POLL_MS,
  LIFECYCLE_WS_OFFLINE_POLL_MS,
  useLifecycleWsConnected
} from '../lib/lifecycle-ws-store';
import { useTabNetworkActive } from './use-tab-network-active';

export { DEVICES_LIST_KEY, FLEET_STATS_KEY } from '../lib/device-query-keys';

export function invalidateDeviceFleetQueries(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: DEVICES_LIST_KEY });
  void qc.invalidateQueries({ queryKey: FLEET_STATS_KEY });
}

export function removeDeviceFromCache(
  qc: QueryClient,
  deviceId: string,
  orgId: string | null | undefined
) {
  if (!orgId) return;
  qc.setQueryData<DeviceOut[]>(
    devicesListQueryKey(orgId),
    (old) => old?.filter((d) => d.id !== deviceId) ?? old
  );
  void qc.invalidateQueries({ queryKey: fleetStatsQueryKey(orgId) });
}

export function useDevices() {
  const wsLive = useLifecycleWsConnected();
  const tabActive = useTabNetworkActive();
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  return useQuery({
    queryKey: devicesListQueryKey(orgId),
    queryFn: devicesApi.list,
    enabled: Boolean(orgId) && tabActive,
    refetchInterval: tabActive
      ? wsLive
        ? LIFECYCLE_WS_LIVE_POLL_MS
        : LIFECYCLE_WS_OFFLINE_POLL_MS
      : false
  });
}

export function useDevicePage(params: DeviceListParams) {
  const wsLive = useLifecycleWsConnected();
  const tabActive = useTabNetworkActive();
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  return useQuery({
    queryKey: [...devicesListQueryKey(orgId), 'page', params],
    queryFn: () => devicesApi.listPage(params),
    enabled: Boolean(orgId) && tabActive,
    placeholderData: (previous) => previous,
    refetchInterval: tabActive
      ? wsLive
        ? LIFECYCLE_WS_LIVE_POLL_MS
        : LIFECYCLE_WS_OFFLINE_POLL_MS
      : false
  });
}

export function useFleetStats() {
  const wsLive = useLifecycleWsConnected();
  const tabActive = useTabNetworkActive();
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  return useQuery({
    queryKey: fleetStatsQueryKey(orgId),
    queryFn: () => devicesApi.fleetStats(),
    enabled: Boolean(orgId) && tabActive,
    staleTime: 15_000,
    refetchInterval: tabActive
      ? wsLive
        ? LIFECYCLE_WS_LIVE_POLL_MS
        : LIFECYCLE_WS_OFFLINE_POLL_MS
      : false
  });
}

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DeviceCreate) => devicesApi.create(data),
    onSuccess: () => {
      invalidateDeviceFleetQueries(qc);
    }
  });
}

export function useDeviceSessions(deviceId: string) {
  return useQuery({
    queryKey: ['device-sessions', deviceId],
    queryFn: () => devicesApi.sessions(deviceId),
    enabled: !!deviceId
  });
}

export function useDeviceBySerial(serial: string) {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  const decoded = decodeURIComponent(serial);
  return useQuery({
    queryKey: [...devicesListQueryKey(orgId), 'by-serial', decoded],
    queryFn: async () => {
      const list = await devicesApi.list();
      const match = list.find(
        (d) =>
          d.serial === decoded || d.adb_serial === decoded || d.id === decoded
      );
      if (!match) throw new Error('device_not_found');
      return match;
    },
    enabled: Boolean(decoded)
  });
}
