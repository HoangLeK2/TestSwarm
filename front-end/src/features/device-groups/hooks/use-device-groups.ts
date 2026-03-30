'use client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  deviceGroupsApi,
  type DeviceGroupCreate,
  type DeviceGroupUpdate
} from '../services/api';

const KEYS = {
  list: ['device-groups'] as const,
  detail: (id: string) => ['device-groups', id] as const
};

export function useDeviceGroups() {
  return useQuery({ queryKey: KEYS.list, queryFn: deviceGroupsApi.list });
}

export function useDeviceGroup(groupId: string) {
  return useQuery({
    queryKey: KEYS.detail(groupId),
    queryFn: () => deviceGroupsApi.get(groupId),
    enabled: !!groupId
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
    mutationFn: ({ groupId, data }: { groupId: string; data: DeviceGroupUpdate }) =>
      deviceGroupsApi.update(groupId, data),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
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
    mutationFn: ({ groupId, deviceIds }: { groupId: string; deviceIds: string[] }) =>
      deviceGroupsApi.addDevices(groupId, deviceIds),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
    }
  });
}

export function useRemoveDeviceFromGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, deviceId }: { groupId: string; deviceId: string }) =>
      deviceGroupsApi.removeDevice(groupId, deviceId),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
    }
  });
}
