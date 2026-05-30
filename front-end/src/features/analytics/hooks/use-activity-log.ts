import { useQuery } from '@tanstack/react-query';
import { analyticsApi } from '../services/api';
import { useOrganization } from '@/features/organization/hooks/use-organization';

export const activityLogKeys = {
  list: (orgId: string | null, limit: number) =>
    ['analytics', 'activity', orgId, limit] as const
};

export function useActivityLog(limit = 50) {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;

  return useQuery({
    queryKey: activityLogKeys.list(orgId, limit),
    queryFn: () => analyticsApi.activity({ limit }),
    enabled: Boolean(orgId),
    refetchInterval: 5_000,
    staleTime: 2_000
  });
}
