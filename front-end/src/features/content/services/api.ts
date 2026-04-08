import { farmApi, deviceFarmBackendBase } from '@/lib/farm-api';

export interface ContentItem {
  id: string;
  collection: string;
  platform: string | null;
  content_type: string;
  title: string | null;
  body: string | null;
  author: string | null;
  author_id: string | null;
  url: string | null;
  likes_count: number | null;
  comments_count: number | null;
  shares_count: number | null;
  views_count: number | null;
  media_urls: string[];
  screenshot_path: string | null;
  tags: string;
  raw_data: Record<string, unknown> | null;
  device_serial: string | null;
  campaign_id: string | null;
  run_id: string | null;
  scenario_name: string | null;
  extracted_at: string | null;
  content_date: string | null;
  created_at: string;
  content_hash: string;
  parent_id: string | null;
  item_level: number;
}

export interface ContentListResponse {
  items: ContentItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ContentFilters {
  collection?: string | null;
  platform?: string | null;
  content_type?: string | null;
  search?: string | null;
  device_serial?: string | null;
  campaign_id?: string | null;
  run_id?: string | null;
  content_hash?: string | null;
  parent_id?: string | null;
  limit?: number;
  offset?: number;
}

export interface ContentStats {
  total_items: number;
  by_platform: Record<string, number>;
  by_collection: Record<string, number>;
  latest_extraction: string | null;
}

export type ExportFormat = 'csv' | 'xlsx';

export const contentApi = {
  /**
   * Trigger a streaming download of the current filtered content.
   * Opens the URL directly so the browser handles the file download.
   */
  exportStream: (filters: ContentFilters, format: ExportFormat): void => {
    const params = new URLSearchParams({ format });
    if (filters.collection) params.set('collection', filters.collection);
    if (filters.platform) params.set('platform', filters.platform);
    if (filters.content_type) params.set('content_type', filters.content_type);
    if (filters.search) params.set('search', filters.search);
    if (filters.device_serial) params.set('device_serial', filters.device_serial);
    if (filters.campaign_id) params.set('campaign_id', filters.campaign_id);
    if (filters.run_id) params.set('run_id', filters.run_id);
    const url = `${deviceFarmBackendBase}/api/content/export/stream?${params.toString()}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `content-export.${format}`;
    a.click();
  },

  list: async (filters?: ContentFilters): Promise<ContentListResponse> => {
    const params: Record<string, unknown> = {
      limit: filters?.limit ?? 50,
      offset: filters?.offset ?? 0,
    };
    if (filters?.collection != null) params.collection = filters.collection;
    if (filters?.platform != null) params.platform = filters.platform;
    if (filters?.content_type != null) params.content_type = filters.content_type;
    if (filters?.search != null) params.search = filters.search;
    if (filters?.device_serial != null) params.device_serial = filters.device_serial;
    if (filters?.campaign_id != null) params.campaign_id = filters.campaign_id;
    if (filters?.run_id != null) params.run_id = filters.run_id;
    if (filters?.content_hash != null) params.content_hash = filters.content_hash;
    if (filters?.parent_id != null) params.parent_id = filters.parent_id;

    return farmApi.get<ContentListResponse>('/content', { params }).then((r) => r.data);
  },

  stats: async (): Promise<ContentStats> =>
    farmApi.get<ContentStats>('/content/stats').then((r) => r.data),

  getItem: async (id: string): Promise<ContentItem> =>
    farmApi.get<ContentItem>(`/content/${id}`).then((r) => r.data),

  deleteItem: async (id: string): Promise<void> => {
    await farmApi.delete(`/content/${id}`);
  },
};
