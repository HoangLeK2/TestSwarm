'use client';

import { useQuery } from '@tanstack/react-query';

import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  buildGroupCatalogParams,
  type GroupCatalogFilters
} from '../lib/group-catalog';
import { externalEntitiesApi } from '../services/api';

export function useGroupCatalog(filters: GroupCatalogFilters) {
  const {
    currentOrg,
    isLoading: organizationLoading,
    isError: organizationError
  } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  const params = buildGroupCatalogParams(filters);

  const query = useQuery({
    queryKey: ['external-entities', 'facebook', 'group', orgId, params],
    queryFn: ({ signal }) => {
      if (!orgId) throw new Error('Organization is required');
      return externalEntitiesApi.list(params, orgId, signal);
    },
    enabled: Boolean(orgId)
  });
  return { ...query, organizationLoading, organizationError };
}
