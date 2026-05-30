import { farmApi } from '@/lib/farm-api';

export type ActivityLogItem = {
  id: string;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  device_serial?: string | null;
  device_display?: string | null;
  org_id?: string | null;
  user_id?: string | null;
  user_name?: string | null;
  method?: string | null;
  path?: string | null;
  route_template?: string | null;
  status_code?: number | null;
  request_id?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  outcome?: string | null;
  duration_ms?: number | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type ActivityLogResponse = {
  total: number;
  offset: number;
  limit: number;
  activities: ActivityLogItem[];
};

export const analyticsApi = {
  activity: (query?: {
    action?: string;
    device_serial?: string;
    offset?: number;
    limit?: number;
  }) =>
    farmApi
      .get<ActivityLogResponse>('/analytics/activity', { params: query })
      .then((r) => r.data)
};
