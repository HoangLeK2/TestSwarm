/**
 * OpenAPI-generated client + factory. Regenerate: `pnpm gen:api`.
 */
export * from './generated/DeviceFarmApi';

import type { ApiConfig, OrganizationOut } from './generated/DeviceFarmApi';
import { DeviceFarmHttpClient } from './generated/DeviceFarmApi';
import { deviceFarmBackendBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';
import { resolveClientOrganizationId } from './client-organization';

/** Must match `OrganizationProvider` storage key. */
const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

type DeviceFarmClientConfig = Omit<
  ApiConfig<{ token: string }>,
  'securityWorker'
> & {
  organizationId?: string;
};

export function createDeviceFarmHttpClient(
  config?: DeviceFarmClientConfig
): DeviceFarmHttpClient<{ token: string }> {
  const { organizationId, ...apiConfig } = config ?? {};
  return new DeviceFarmHttpClient({
    baseURL: deviceFarmBackendBase,
    ...apiConfig,
    securityWorker: async (securityData) => {
      const token = securityData?.token ?? tokenStorage.getAuthToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
      if (typeof window !== 'undefined') {
        const orgId = resolveClientOrganizationId(
          organizationId,
          localStorage.getItem(CURRENT_ORG_STORAGE_KEY)
        );
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

let deviceFarmApiSingleton: DeviceFarmHttpClient<{ token: string }> | null =
  null;

/** Shared generated client for product API routes (`/api/*`). */
export function getDeviceFarmApi(): DeviceFarmHttpClient<{ token: string }> {
  if (!deviceFarmApiSingleton) {
    deviceFarmApiSingleton = createDeviceFarmHttpClient({ secure: true });
  }
  return deviceFarmApiSingleton;
}
