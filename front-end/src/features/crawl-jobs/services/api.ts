import { farmApi } from '@/lib/farm-api';

export type CrawlJob = {
  id: string;
  name: string;
  device_serial: string;
  campaign_id: string | null;
  group_id: string;
  app: string;
  status: string;
  total_posts: number;
  total_scrolls: number;
  created_at: string | null;
  completed_at: string | null;
};

export type CrawlPost = {
  id: string;
  job_id: string;
  author: string;
  text: string;
  timestamp_raw: string;
  reactions: string | null;
  comments: string | null;
  shares: string | null;
  source_index: number;
  scraped_at: string | null;
};

export type EnqueueCrawlJobInput = {
  campaign_id?: string;
  scenario_id?: string;
  group_id: string;
  max_posts?: number;
  max_scrolls?: number;
  app: 'chrome' | 'facebook' | 'facebook_lite';
  scroll_pause?: number;
  wait_load?: number;
  expand_posts?: boolean;
  auto_append_crawl?: boolean;
  name?: string;
};

export type EnqueueCrawlJobResult = {
  task_id: string;
  job_id?: string;
  serial: string;
  group_id: string;
  campaign_id?: string;
  status: string;
};

export const crawlJobsApi = {
  list: (params?: { limit?: number; offset?: number; campaignId?: string }) => {
    const limit = params?.limit ?? 50;
    const offset = params?.offset ?? 0;
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset)
    });
    if (params?.campaignId) query.set('campaign_id', params.campaignId);
    return farmApi
      .get<CrawlJob[]>(`/crawl/jobs?${query.toString()}`)
      .then((r) => r.data);
  },
  getPosts: (jobId: string, limit = 200, offset = 0) =>
    farmApi
      .get<CrawlPost[]>(`/crawl/jobs/${jobId}/posts?limit=${limit}&offset=${offset}`)
      .then((r) => r.data),
  enqueue: (serial: string, data: EnqueueCrawlJobInput) =>
    farmApi
      .post<EnqueueCrawlJobResult>(`/devices/${encodeURIComponent(serial)}/crawl/jobs/enqueue`, data)
      .then((r) => r.data)
};
