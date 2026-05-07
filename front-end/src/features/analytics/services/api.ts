import { farmApi } from '@/lib/farm-api';

export type ActivityLogItem = {
  id: string;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  device_serial?: string | null;
  user_id?: string | null;
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
