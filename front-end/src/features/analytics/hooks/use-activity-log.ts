'use client';

import { useQuery } from '@tanstack/react-query';
import { analyticsApi } from '../services/api';
import { useOrganization } from '@/features/organization/hooks/use-organization';

export type ActivityLogQuery = {
  action?: string;
  device_serial?: string;
  offset?: number;
  limit?: number;
};

export const activityLogKeys = {
  list: (orgId: string | null, query: ActivityLogQuery) =>
    ['analytics', 'activity', orgId, query] as const
};

export function useActivityLog(query: ActivityLogQuery = {}) {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  const limit = query.limit ?? 50;
  const offset = query.offset ?? 0;

  return useQuery({
    queryKey: activityLogKeys.list(orgId, { ...query, limit, offset }),
    queryFn: () =>
      analyticsApi.activity({
        action: query.action,
        device_serial: query.device_serial,
        offset,
        limit
      }),
    enabled: Boolean(orgId),
    refetchInterval: offset === 0 ? 5_000 : false,
    staleTime: 2_000
  });
}
