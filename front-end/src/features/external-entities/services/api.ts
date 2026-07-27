import {
  createDeviceFarmHttpClient,
  getDeviceFarmApi
} from '@/features/device-farm/services/client';
import type { ExternalEntityOut } from '@/features/device-farm/services/generated/DeviceFarmApi';

type ListExternalEntitiesQuery = NonNullable<
  Parameters<
    ReturnType<
      typeof getDeviceFarmApi
    >['api']['listExternalEntitiesRouteApiExternalEntitiesGet']
  >[0]
>;

export type ExternalEntityCatalogItem = ExternalEntityOut;

export const externalEntitiesApi = {
  list: async (query: ListExternalEntitiesQuery, organizationId?: string) => {
    const client = organizationId
      ? createDeviceFarmHttpClient({
          secure: true,
          organizationId
        })
      : getDeviceFarmApi();
    const response =
      await client.api.listExternalEntitiesRouteApiExternalEntitiesGet(query);
    return response.data;
  }
};
