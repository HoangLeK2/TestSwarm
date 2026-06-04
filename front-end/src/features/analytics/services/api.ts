/**
 * Analytics API — thin wrapper over OpenAPI-generated client.
 * Regenerate: `pnpm gen:api:sync` (backend `uv run export-openapi` first).
 */
import { getDeviceFarmApi } from '@/features/device-farm/services/client';
import type {
  ActivityLogListOut,
  ActivityLogOut,
  AnalyticsAdhocOut,
  AnalyticsPointOut,
  AnalyticsSummaryOut,
  AnalyticsTimeseriesOut
} from '@/features/device-farm/services/generated/DeviceFarmApi';

export type ActivityLogItem = ActivityLogOut;
export type ActivityLogResponse = ActivityLogListOut;
export type AnalyticsPoint = AnalyticsPointOut;
export type AnalyticsTimeseriesResponse = AnalyticsTimeseriesOut;
export type AnalyticsSummaryResponse = AnalyticsSummaryOut;
export type AnalyticsAdhocResponse = AnalyticsAdhocOut;

export type AnalyticsDimension =
  | 'device'
  | 'campaign'
  | 'platform'
  | 'account'
  | 'event_type';

export type AnalyticsTimeseriesQuery = {
  dimension: AnalyticsDimension;
  resource_id?: string;
  event_type?: string;
  from: string;
  to: string;
  granularity?: 'day' | 'week';
};

export type AnalyticsAdhocQuery = {
  from: string;
  to: string;
  dimensions: string[];
  metric?: string;
  filters?: Record<string, string>;
  limit?: number;
};

export type AnalyticsAuditExportQuery = {
  from: string;
  to: string;
  action?: string;
  actor?: string;
  resource_type?: string;
  resource_id?: string;
};

const df = () => getDeviceFarmApi().api;

export const analyticsApi = {
  activity: async (query?: {
    action?: string;
    device_serial?: string;
    offset?: number;
    limit?: number;
  }) => (await df().listActivityApiAnalyticsActivityGet(query)).data,

  summary: async (windowDays = 7) =>
    (await df().summaryApiAnalyticsSummaryGet({ window_days: windowDays }))
      .data,

  timeseries: async (query: AnalyticsTimeseriesQuery) =>
    (
      await df().timeseriesApiAnalyticsTimeseriesGet({
        dimension: query.dimension,
        resource_id: query.resource_id,
        event_type: query.event_type,
        from: query.from,
        to: query.to,
        granularity: query.granularity ?? 'day'
      })
    ).data,

  adhocQuery: async (body: AnalyticsAdhocQuery) =>
    (await df().adhocQueryApiAnalyticsAdhocQueryPost(body)).data,

  auditExport: async (
    query: AnalyticsAuditExportQuery
  ): Promise<{ blob: Blob; filename: string }> => {
    const response = await df().auditExportApiAnalyticsAuditExportGet({
      from: query.from,
      to: query.to,
      action: query.action,
      actor: query.actor,
      resource_type: query.resource_type,
      resource_id: query.resource_id
    });
    const csv =
      typeof response.data === 'string'
        ? response.data
        : new TextDecoder().decode(response.data as ArrayBuffer);
    return {
      blob: new Blob([csv], { type: 'text/csv;charset=utf-8' }),
      filename: `audit-${query.from}-${query.to}.csv`
    };
  }
};
