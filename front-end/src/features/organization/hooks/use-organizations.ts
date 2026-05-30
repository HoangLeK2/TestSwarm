'use client';

import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import {
  listOrganizations,
  type OrganizationListParams
} from '../services/farm-org-api';

const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

export const organizationQueryKeys = {
  list: (params: OrganizationListParams) =>
    ['organization', 'list', params] as const,
  infinite: (search: string) => ['organization', 'list', 'infinite', search] as const
};

/** Bootstrap org list for provider (includes stored current org via ensure_id). */
export function useOrganizationsQuery() {
  const ensureId =
    typeof window !== 'undefined'
      ? localStorage.getItem(CURRENT_ORG_STORAGE_KEY)?.trim() || undefined
      : undefined;

  return useQuery({
    queryKey: organizationQueryKeys.list({ limit: 100, ensure_id: ensureId }),
    queryFn: () =>
      listOrganizations({ limit: 100, offset: 0, ensure_id: ensureId }),
    staleTime: 60_000,
    select: (data) => data.items ?? [],
  });
}

export function useOrganizationsPaginated(
  page: number,
  pageSize: number,
  search: string,
  options?: { enabled?: boolean }
) {
  const offset = page * pageSize;
  return useQuery({
    queryKey: organizationQueryKeys.list({
      search: search || undefined,
      offset,
      limit: pageSize
    }),
    queryFn: () =>
      listOrganizations({
        search: search.trim() || undefined,
        offset,
        limit: pageSize
      }),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    enabled: options?.enabled ?? true
  });
}

export function useOrganizationsInfinite(search: string) {
  const pageSize = 20;
  return useInfiniteQuery({
    queryKey: organizationQueryKeys.infinite(search.trim()),
    queryFn: ({ pageParam = 0 }) =>
      listOrganizations({
        search: search.trim() || undefined,
        offset: pageParam,
        limit: pageSize
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const items = last?.items ?? [];
      const offset = last?.offset ?? 0;
      const total = last?.total ?? items.length;
      const next = offset + items.length;
      return next < total ? next : undefined;
    },
    staleTime: 30_000
  });
}
