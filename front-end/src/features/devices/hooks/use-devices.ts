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
  qc.setQueryData<DeviceOut[]>(devicesListQueryKey(orgId), (old) =>
    old?.filter((d) => d.id !== deviceId) ?? old
  );
  void qc.invalidateQueries({ queryKey: fleetStatsQueryKey(orgId) });
}

export function useDevices() {
  const wsLive = useLifecycleWsConnected();
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  return useQuery({
    queryKey: devicesListQueryKey(orgId),
    queryFn: devicesApi.list,
    enabled: Boolean(orgId),
    refetchInterval: wsLive
      ? LIFECYCLE_WS_LIVE_POLL_MS
      : LIFECYCLE_WS_OFFLINE_POLL_MS
  });
}

export function useFleetStats() {
  const wsLive = useLifecycleWsConnected();
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  return useQuery({
    queryKey: fleetStatsQueryKey(orgId),
    queryFn: () => devicesApi.fleetStats(),
    enabled: Boolean(orgId),
    staleTime: 15_000,
    refetchInterval: wsLive
      ? LIFECYCLE_WS_LIVE_POLL_MS
      : LIFECYCLE_WS_OFFLINE_POLL_MS
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
