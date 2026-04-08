'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { contentApi, type ContentFilters, type ContentItem, type ContentListResponse, type ContentStats } from '../services/api';

const PAGE_SIZE = 50;

export function useContent(initialFilters?: ContentFilters) {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<ContentFilters>(initialFilters ?? {});
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (f: ContentFilters, pageNum: number) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    try {
      const res: ContentListResponse = await contentApi.list({
        ...f,
        limit: PAGE_SIZE,
        offset: pageNum * PAGE_SIZE,
      });
      if (!ctrl.signal.aborted) {
        setItems(res.items);
        setTotal(res.total);
      }
    } catch (e: unknown) {
      if (!ctrl.signal.aborted) {
        setError(e instanceof Error ? e.message : 'Lỗi tải dữ liệu');
      }
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(filters, page);
  }, [filters, page, load]);

  const applyFilters = useCallback((f: ContentFilters) => {
    setFilters(f);
    setPage(0);
  }, []);

  const deleteItem = useCallback(async (id: string) => {
    await contentApi.deleteItem(id);
    setItems((prev) => prev.filter((it) => it.id !== id));
    setTotal((prev) => prev - 1);
  }, []);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return { items, total, page, totalPages, loading, error, filters, applyFilters, setPage, deleteItem, reload: () => load(filters, page) };
}

export function useContentStats() {
  const [stats, setStats] = useState<ContentStats | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    contentApi.stats().then(setStats).catch(() => {}).finally(() => setLoading(false));
  }, []);

  return { stats, loading };
}
