import { useMutation, useQuery } from '@tanstack/react-query';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  analyticsApi,
  type AnalyticsAdhocQuery,
  type AnalyticsAuditExportQuery,
  type AnalyticsTimeseriesQuery
} from '../services/api';

export const analyticsKeys = {
  summary: (orgId: string | null, windowDays: number) =>
    ['analytics', 'summary', orgId, windowDays] as const,
  timeseries: (orgId: string | null, query: AnalyticsTimeseriesQuery) =>
    ['analytics', 'timeseries', orgId, query] as const
};

export function useAnalyticsSummary(windowDays = 7) {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;

  return useQuery({
    queryKey: analyticsKeys.summary(orgId, windowDays),
    queryFn: () => analyticsApi.summary(windowDays),
    enabled: Boolean(orgId),
    staleTime: 60_000
  });
}

export function useAnalyticsTimeseries(
  query: AnalyticsTimeseriesQuery | null
) {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;

  return useQuery({
    queryKey: analyticsKeys.timeseries(orgId, query!),
    queryFn: () => analyticsApi.timeseries(query!),
    enabled: Boolean(orgId && query),
    staleTime: 60_000
  });
}

export function useAnalyticsAdhocQuery() {
  return useMutation({
    mutationFn: (body: AnalyticsAdhocQuery) => analyticsApi.adhocQuery(body)
  });
}

export function useAnalyticsAuditExport() {
  return useMutation({
    mutationFn: async (query: AnalyticsAuditExportQuery) => {
      const { blob, filename } = await analyticsApi.auditExport(query);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    }
  });
}
