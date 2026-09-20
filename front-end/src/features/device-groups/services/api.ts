import { farmApi } from '@/lib/farm-api';
import type {
  DeviceGroupOut,
  DeviceGroupDetailOut,
  DeviceGroupCreate,
  DeviceGroupUpdate
} from '../../device-farm/services/generated/DeviceFarmApi';
import type { DeviceOut } from '../../devices/services/manage-api';

export type {
  DeviceGroupOut,
  DeviceGroupDetailOut,
  DeviceGroupCreate,
  DeviceGroupUpdate
};

export type AvailableGroupDevicesParams = {
  q?: string;
  limit?: number;
  offset?: number;
};

export type AvailableGroupDevicesOut = {
  items: DeviceOut[];
  total: number;
  offset: number;
  limit: number;
};

export const deviceGroupsApi = {
  list: () =>
    farmApi.get<DeviceGroupOut[]>('/device-groups').then((r) => r.data),
  get: (groupId: string) =>
    farmApi
      .get<DeviceGroupDetailOut>(`/device-groups/${groupId}`)
      .then((r) => r.data),
  create: (data: DeviceGroupCreate) =>
    farmApi.post<DeviceGroupOut>('/device-groups', data).then((r) => r.data),
  update: (groupId: string, data: DeviceGroupUpdate) =>
    farmApi
      .patch<DeviceGroupOut>(`/device-groups/${groupId}`, data)
      .then((r) => r.data),
  delete: (groupId: string) =>
    farmApi.delete(`/device-groups/${groupId}`).then((r) => r.data),
  availableDevices: (
    groupId: string,
    { q, limit = 20, offset = 0 }: AvailableGroupDevicesParams = {}
  ) =>
    farmApi
      .get<AvailableGroupDevicesOut>(
        `/device-groups/${encodeURIComponent(groupId)}/available-devices`,
        {
          params: {
            q: q || undefined,
            limit,
            offset
          }
        }
      )
      .then((r) => r.data),
  addDevices: (groupId: string, deviceIds: string[]) =>
    farmApi
      .post(`/device-groups/${groupId}/devices`, { device_ids: deviceIds })
      .then((r) => r.data),
  removeDevice: (groupId: string, deviceId: string) =>
    farmApi
      .delete(`/device-groups/${groupId}/devices/${deviceId}`)
      .then((r) => r.data)
};
