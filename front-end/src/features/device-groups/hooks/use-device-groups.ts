'use client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  deviceGroupsApi,
  type AvailableGroupDevicesParams,
  type DeviceGroupCreate,
  type DeviceGroupUpdate
} from '../services/api';

const KEYS = {
  list: ['device-groups'] as const,
  detail: (id: string) => ['device-groups', id] as const,
  availableDevices: (id: string, params: AvailableGroupDevicesParams) =>
    ['device-groups', id, 'available-devices', params] as const
};
const DEVICE_GROUPS_STALE_MS = 30_000;

export function useDeviceGroups() {
  return useQuery({
    queryKey: KEYS.list,
    queryFn: deviceGroupsApi.list,
    staleTime: DEVICE_GROUPS_STALE_MS
  });
}

export function useDeviceGroup(
  groupId: string,
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: KEYS.detail(groupId),
    queryFn: () => deviceGroupsApi.get(groupId),
    enabled: !!groupId && (options?.enabled ?? true)
  });
}

export function useAvailableGroupDevices(
  groupId: string,
  params: AvailableGroupDevicesParams,
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: KEYS.availableDevices(groupId, params),
    queryFn: () => deviceGroupsApi.availableDevices(groupId, params),
    enabled: !!groupId && (options?.enabled ?? true),
    placeholderData: (previous) => previous
  });
}

export function useCreateDeviceGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DeviceGroupCreate) => deviceGroupsApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useUpdateDeviceGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      groupId,
      data
    }: {
      groupId: string;
      data: DeviceGroupUpdate;
    }) => deviceGroupsApi.update(groupId, data),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
      qc.invalidateQueries({
        queryKey: ['device-groups', groupId, 'available-devices']
      });
    }
  });
}

export function useDeleteDeviceGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) => deviceGroupsApi.delete(groupId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useAddDevicesToGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      groupId,
      deviceIds
    }: {
      groupId: string;
      deviceIds: string[];
    }) => deviceGroupsApi.addDevices(groupId, deviceIds),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
      qc.invalidateQueries({
        queryKey: ['device-groups', groupId, 'available-devices']
      });
    }
  });
}

export function useRemoveDeviceFromGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      groupId,
      deviceId
    }: {
      groupId: string;
      deviceId: string;
    }) => deviceGroupsApi.removeDevice(groupId, deviceId),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
      qc.invalidateQueries({
        queryKey: ['device-groups', groupId, 'available-devices']
      });
    }
  });
}
