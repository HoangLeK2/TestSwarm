import { farmApi, deviceFarmBackendBase } from '@/lib/farm-api';
import { filenameFromContentDisposition } from '@/features/content/lib/download';

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
  /** @deprecated Prefer execution_id — kept for list compatibility */
  run_id?: string | null;
  execution_id?: string | null;
  scenario_name: string | null;
  extracted_at: string | null;
  content_date: string | null;
  created_at: string;
  content_hash: string;
  parent_id: string | null;
  parent_item_id?: string | null;
  parent_item_hash?: string | null;
  parent_item_author?: string | null;
  parent_item_body?: string | null;
  parent_item_content_type?: string | null;
  item_level: number;
}

export type ContentArtifactKind = 'image' | 'xml' | 'json' | 'text';

export interface ContentArtifact {
  id: string;
  kind: ContentArtifactKind | string;
  label: string;
  source: string;
  url: string | null;
  inline: boolean;
  size_bytes: number | null;
  status: string;
  mime_type: string | null;
}

export interface ContentDetail extends ContentItem {
  artifacts: ContentArtifact[];
  payload: Record<string, unknown>;
}

export interface ContentPermalink {
  token: string;
  path: string;
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

function artifactApiPath(resolvedUrl: string): string {
  const base = deviceFarmBackendBase;
  if (resolvedUrl.startsWith(base)) {
    const rest = resolvedUrl.slice(base.length);
    if (rest.startsWith('/api/')) return rest.slice(4);
    if (rest.startsWith('/api')) return rest.slice(4) || '/';
    return rest.startsWith('/') ? rest : `/${rest}`;
  }
  if (resolvedUrl.startsWith('/api/')) return resolvedUrl.slice(4);
  if (resolvedUrl.startsWith('/')) return resolvedUrl;
  return resolvedUrl;
}

export const contentApi = {
  /**
   * Stream export via backend `/api/content/export/stream`.
   * Returns blob for caller to download (service layer — no fetch in components).
   */
  exportStream: async (
    filters: ContentFilters,
    format: ExportFormat
  ): Promise<{ blob: Blob; filename: string }> => {
    const params: Record<string, string> = { format };
    if (filters.collection) params.collection = filters.collection;
    if (filters.platform) params.platform = filters.platform;
    if (filters.content_type) params.content_type = filters.content_type;
    if (filters.search) params.search = filters.search;
    if (filters.device_serial) params.device_serial = filters.device_serial;
    if (filters.campaign_id) params.campaign_id = filters.campaign_id;
    if (filters.run_id) params.execution_id = filters.run_id;

    const response = await farmApi.get<Blob>('/content/export/stream', {
      params,
      responseType: 'blob'
    });
    const disposition = response.headers['content-disposition'] as
      | string
      | undefined;
    const filename =
      filenameFromContentDisposition(disposition) ?? `content-export.${format}`;
    return { blob: response.data as Blob, filename };
  },

  fetchArtifactText: async (resolvedUrl: string): Promise<string> => {
    const path = artifactApiPath(resolvedUrl);
    const response = await farmApi.get<string>(path, {
      responseType: 'text' as 'json',
      transformResponse: [(data: string) => data]
    });
    return String(response.data ?? '');
  },

  fetchArtifactBlob: async (resolvedUrl: string): Promise<Blob> => {
    const path = artifactApiPath(resolvedUrl);
    const response = await farmApi.get<Blob>(path, { responseType: 'blob' });
    const data = response.data;
    if (data instanceof Blob) return data;
    if (data instanceof ArrayBuffer) {
      const contentType = String(
        response.headers['content-type'] ?? 'image/png'
      );
      return new Blob([data], { type: contentType });
    }
    throw new TypeError('Artifact download did not return a Blob');
  },

  list: async (filters?: ContentFilters): Promise<ContentListResponse> => {
    const params: Record<string, unknown> = {
      limit: filters?.limit ?? 50,
      offset: filters?.offset ?? 0
    };
    if (filters?.collection != null) params.collection = filters.collection;
    if (filters?.platform != null) params.platform = filters.platform;
    if (filters?.content_type != null)
      params.content_type = filters.content_type;
    if (filters?.search != null) params.search = filters.search;
    if (filters?.device_serial != null)
      params.device_serial = filters.device_serial;
    if (filters?.campaign_id != null) params.campaign_id = filters.campaign_id;
    if (filters?.run_id != null) params.run_id = filters.run_id;
    if (filters?.content_hash != null)
      params.content_hash = filters.content_hash;
    if (filters?.parent_id != null) params.parent_id = filters.parent_id;

    return farmApi
      .get<ContentListResponse>('/content', { params })
      .then((r) => r.data);
  },

  stats: async (): Promise<ContentStats> =>
    farmApi.get<ContentStats>('/content/stats').then((r) => r.data),

  getItem: async (id: string): Promise<ContentItem> => contentApi.getDetail(id),

  getDetail: async (
    id: string,
    shareToken?: string | null
  ): Promise<ContentDetail> =>
    farmApi
      .get<ContentDetail>(`/content/${id}`, {
        params: shareToken ? { share: shareToken } : undefined
      })
      .then((r) => r.data),

  listChildren: async (
    itemId: string,
    opts?: { limit?: number; offset?: number }
  ): Promise<ContentListResponse> =>
    farmApi
      .get<ContentListResponse>(`/content/${itemId}/children`, {
        params: {
          limit: opts?.limit ?? 100,
          offset: opts?.offset ?? 0
        }
      })
      .then((r) => r.data),

  createPermalink: async (id: string): Promise<ContentPermalink> =>
    farmApi
      .post<ContentPermalink>(`/content/${id}/permalink`)
      .then((r) => r.data),

  downloadArtifact: async (
    contentId: string,
    artifactId: string,
    shareToken?: string | null
  ): Promise<{ blob: Blob; filename: string | null }> => {
    const response = await farmApi.get(
      `/content/${contentId}/artifacts/${encodeURIComponent(artifactId)}/download`,
      {
        responseType: 'blob',
        params: shareToken ? { share: shareToken } : undefined
      }
    );
    const disposition = response.headers['content-disposition'] as
      | string
      | undefined;
    return {
      blob: response.data as Blob,
      filename: filenameFromContentDisposition(disposition)
    };
  },

  deleteItem: async (id: string): Promise<void> => {
    await farmApi.delete(`/content/${id}`);
  }
};
