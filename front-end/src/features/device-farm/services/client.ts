/**
 * OpenAPI-generated client + factory. Regenerate: `pnpm gen:api`.
 */
export * from './generated/DeviceFarmApi';

import type { ApiConfig, OrganizationOut } from './generated/DeviceFarmApi';
import { DeviceFarmHttpClient } from './generated/DeviceFarmApi';
import { deviceFarmBackendBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';

export function createDeviceFarmHttpClient(
  config?: Omit<ApiConfig<{ token: string }>, 'securityWorker'>
): DeviceFarmHttpClient<{ token: string }> {
  return new DeviceFarmHttpClient({
    baseURL: deviceFarmBackendBase,
    ...config,
    securityWorker: async (securityData) => {
      const token = securityData?.token ?? tokenStorage.getAuthToken();
      if (!token) return {};
      return { headers: { Authorization: `Bearer ${token}` } };
    }
  });
}

/** Alias aligned with older `ProtoOrganization` name. */
export type ProtoOrganization = OrganizationOut;
