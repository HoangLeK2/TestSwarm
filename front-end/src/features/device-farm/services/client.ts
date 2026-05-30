/**
 * OpenAPI-generated client + factory. Regenerate: `pnpm gen:api`.
 */
export * from './generated/DeviceFarmApi';

import type { ApiConfig, OrganizationOut } from './generated/DeviceFarmApi';
import { DeviceFarmHttpClient } from './generated/DeviceFarmApi';
import { deviceFarmBackendBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';

/** Must match `OrganizationProvider` storage key. */
const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

export function createDeviceFarmHttpClient(
  config?: Omit<ApiConfig<{ token: string }>, 'securityWorker'>
): DeviceFarmHttpClient<{ token: string }> {
  return new DeviceFarmHttpClient({
    baseURL: deviceFarmBackendBase,
    ...config,
    securityWorker: async (securityData) => {
      const token = securityData?.token ?? tokenStorage.getAuthToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
      if (typeof window !== 'undefined') {
        const orgId = localStorage.getItem(CURRENT_ORG_STORAGE_KEY)?.trim();
        if (orgId) {
          headers['X-Organization-Id'] = orgId;
        }
      }
      if (!Object.keys(headers).length) return {};
      return { headers };
    }
  });
}

/** Alias aligned with older `ProtoOrganization` name. */
export type ProtoOrganization = OrganizationOut;
