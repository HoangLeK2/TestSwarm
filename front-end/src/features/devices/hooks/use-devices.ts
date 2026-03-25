'use client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { devicesApi, type DeviceCreate } from '../services/manage-api';

const KEYS = { list: ['devices'] as const };

export function useDevices() {
  return useQuery({ queryKey: KEYS.list, queryFn: devicesApi.list });
}

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DeviceCreate) => devicesApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useDeviceSessions(deviceId: string) {
  return useQuery({
    queryKey: ['device-sessions', deviceId],
    queryFn: () => devicesApi.sessions(deviceId),
    enabled: !!deviceId
  });
}
