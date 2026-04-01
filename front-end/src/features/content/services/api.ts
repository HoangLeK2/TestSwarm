import { farmApi } from '@/lib/farm-api';

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
  limit?: number;
  offset?: number;
}

export interface CampaignRun {
  id: string;
  campaign_id: string;
  status: 'running' | 'completed' | 'failed';
  device_serials: string[];
  workflow_ids: string[];
  scenarios_count: number;
  total_saved: number;
  total_duplicate: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface CampaignRunListResponse {
  items: CampaignRun[];
  total: number;
}

export interface RunContentStats {
  run_id: string;
  total_items: number;
  latest_extraction: string | null;
}

export interface ContentStats {
  total_items: number;
  by_platform: Record<string, number>;
  by_collection: Record<string, number>;
  latest_extraction: string | null;
}

export const campaignRunApi = {
  listRuns: async (campaignId: string, params?: { limit?: number; offset?: number }): Promise<CampaignRunListResponse> => {
    const res = await farmApi.campaigns.listRunsApiCampaignsCampaignIdRunsGet(campaignId, params);
    return res.data as CampaignRunListResponse;
  },

  getRun: async (campaignId: string, runId: string): Promise<CampaignRun> => {
    const res = await farmApi.campaigns.getRunApiCampaignsCampaignIdRunsRunIdGet(campaignId, runId);
    return res.data as CampaignRun;
  },

  runStats: async (campaignId: string, runId: string): Promise<RunContentStats> => {
    const res = await farmApi.campaigns.runContentStatsApiCampaignsCampaignIdRunsRunIdContentStatsGet(campaignId, runId);
    return res.data as RunContentStats;
  },
};

export const contentApi = {
  list: async (filters?: ContentFilters): Promise<ContentListResponse> => {
    const res = await farmApi.content.listContentApiContentGet({
      ...filters,
      limit: filters?.limit ?? 50,
      offset: filters?.offset ?? 0,
    });
    return res.data as ContentListResponse;
  },

  stats: async (): Promise<ContentStats> => {
    const res = await farmApi.content.getStatsApiContentStatsGet();
    return res.data as ContentStats;
  },

  getItem: async (id: string): Promise<ContentItem> => {
    const res = await farmApi.content.getContentItemApiContentItemIdGet(id);
    return res.data as ContentItem;
  },

  deleteItem: async (id: string): Promise<void> => {
    await farmApi.content.deleteContentItemApiContentItemIdDelete(id);
  },
};
