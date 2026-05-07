import { useQuery } from '@tanstack/react-query';
import { analyticsApi } from '../services/api';

export const activityLogKeys = {
  list: (limit: number) => ['analytics', 'activity', limit] as const
};

export function useActivityLog(limit = 50) {
  return useQuery({
    queryKey: activityLogKeys.list(limit),
    queryFn: () => analyticsApi.activity({ limit }),
    refetchInterval: 5_000,
    staleTime: 2_000
  });
}
