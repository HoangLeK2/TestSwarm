'use client';

import { useCallback, useEffect, useState } from 'react';
import { contentApi, type ContentDetail } from '../services/api';

export function useContentDetail(
  contentId: string | null,
  shareToken?: string | null
) {
  const [detail, setDetail] = useState<ContentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!contentId) return;
    setLoading(true);
    setError(null);
    setStatusCode(null);
    try {
      const data = await contentApi.getDetail(contentId, shareToken);
      setDetail(data);
    } catch (e: unknown) {
      const status =
        e && typeof e === 'object' && 'response' in e
          ? (e as { response?: { status?: number } }).response?.status
          : undefined;
      setStatusCode(status ?? null);
      setError(e instanceof Error ? e.message : 'Failed to load content');
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [contentId, shareToken]);

  useEffect(() => {
    void load();
  }, [load]);

  return { detail, loading, error, statusCode, reload: load };
}
