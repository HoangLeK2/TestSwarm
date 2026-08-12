import {
  createDeviceFarmHttpClient,
  getDeviceFarmApi
} from '@/features/device-farm/services/client';
import { farmApi } from '@/lib/farm-api';
import type {
  DeviceTargetGroupsOut,
  ExternalEntityObserveIn,
  ExternalEntityObserveOut,
  ExternalEntityOut
} from '@/features/device-farm/services/generated/DeviceFarmApi';

type ListExternalEntitiesQuery = NonNullable<
  Parameters<
    ReturnType<
      typeof getDeviceFarmApi
    >['api']['listExternalEntitiesRouteApiExternalEntitiesGet']
  >[0]
>;

export type ExternalEntityCatalogItem = ExternalEntityOut;
export type CreatePageTargetIn = {
  displayName: string;
  canonicalUrl?: string | null;
  externalId?: string | null;
  searchQuery?: string | null;
};
export type SyncAuthorsFromContentIn = {
  collection?: string | null;
  campaign_id?: string | null;
  execution_id?: string | null;
  content_types?: string[];
  dry_run?: boolean;
  limit?: number;
};
export type SyncAuthorsFromContentOut = {
  scanned_count: number;
  valid_count: number;
  created_count: number;
  existing_count: number;
  skipped_existing_count: number;
  skipped_count: number;
  skipped_anonymous_count: number;
  skipped_invalid_count: number;
};
export type DeviceTargetItem = DeviceTargetGroupsOut['groups'][number] & {
  platform: string;
  entity_type: string;
};
export type DeviceTargetsOut = Omit<DeviceTargetGroupsOut, 'groups'> & {
  groups: DeviceTargetItem[];
};

export const externalEntitiesApi = {
  list: async (
    query: ListExternalEntitiesQuery,
    organizationId?: string,
    signal?: AbortSignal
  ) => {
    const client = organizationId
      ? createDeviceFarmHttpClient({
          secure: true,
          organizationId
        })
      : getDeviceFarmApi();
    const response =
      await client.api.listExternalEntitiesRouteApiExternalEntitiesGet(query, {
        signal
      });
    return response.data;
  },
  createPageTarget: async (
    body: CreatePageTargetIn,
    organizationId: string
  ): Promise<ExternalEntityObserveOut> => {
    const displayName = body.displayName.trim();
    const canonicalUrl = body.canonicalUrl?.trim() || null;
    const externalId = body.externalId?.trim() || null;
    const searchQuery = body.searchQuery?.trim() || displayName;
    const payload: ExternalEntityObserveIn = {
      platform: 'facebook',
      entity_type: 'page',
      display_name: displayName,
      canonical_url: canonicalUrl,
      external_id: externalId,
      status: 'active',
      query: searchQuery,
      attributes: {
        source: 'manual_ui',
        search_query: searchQuery,
        locator: {
          search_query: searchQuery,
          ...(canonicalUrl ? { canonical_url: canonicalUrl } : {}),
          ...(externalId ? { external_id: externalId } : {})
        }
      },
      raw_data: {
        source: 'manual_ui'
      }
    };
    const client = createDeviceFarmHttpClient({
      secure: true,
      organizationId
    });
    const response =
      await client.api.observeExternalEntityRouteApiExternalEntitiesObservePost(
        payload
      );
    return response.data;
  },
  syncAuthorsFromContent: async (
    body: SyncAuthorsFromContentIn
  ): Promise<SyncAuthorsFromContentOut> => {
    const response = await farmApi.post<SyncAuthorsFromContentOut>(
      '/external-entities/sync-authors-from-content',
      body
    );
    return response.data;
  },
  listDeviceTargetGroups: async (
    deviceId: string,
    organizationId: string,
    signal?: AbortSignal
  ): Promise<DeviceTargetsOut> => {
    const client = createDeviceFarmHttpClient({ secure: true, organizationId });
    const response =
      await client.api.listDeviceTargetGroupsRouteApiDevicesDeviceIdTargetGroupsGet(
        deviceId,
        { signal }
      );
    return response.data as DeviceTargetsOut;
  },
  replaceDeviceTargetGroups: async (
    deviceId: string,
    groupIds: string[],
    organizationId: string
  ): Promise<DeviceTargetsOut> => {
    const client = createDeviceFarmHttpClient({ secure: true, organizationId });
    const response =
      await client.api.replaceDeviceTargetGroupsRouteApiDevicesDeviceIdTargetGroupsPut(
        deviceId,
        { external_entity_ids: groupIds }
      );
    return response.data as DeviceTargetsOut;
  }
};
