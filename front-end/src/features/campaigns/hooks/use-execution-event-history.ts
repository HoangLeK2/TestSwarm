'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { ExecutionEventOut } from '../../device-farm/services/generated/DeviceFarmApi';
import { executionsApi } from '../services/api';
import { foldEventsToStepLog } from '../lib/execution-event-utils';
import type { StepLogEntry } from '../types';

/** `/executions/{id}/events` clamps `limit` to 1..500. */
const PAGE_SIZE = 500;
/** 20k events is already far past what a dialog can usefully render. */
const MAX_PAGES = 40;

async function fetchAllEvents(
  executionId: string
): Promise<{ items: ExecutionEventOut[]; truncated: boolean }> {
  const items: ExecutionEventOut[] = [];
  let since: string | null = null;

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const res = await executionsApi.listEvents(executionId, {
      since,
      limit: PAGE_SIZE
    });
    items.push(...(res.items ?? []));
    const last = res.items?.at(-1)?.event_id ?? null;
    // No cursor to advance means another request would replay the same page.
    if (!res.has_more || !last || last === since) {
      return { items, truncated: false };
    }
    since = last;
  }
  return { items, truncated: true };
}

/**
 * Full event history for one execution, folded into per-run step rows.
 *
 * The task-log endpoint caps events at 500 with no way to page further, which a
 * single 20-iteration loop already blows past — so read the event feed directly.
 * A finished run's events never change, hence the long staleTime and no polling.
 */
export function useExecutionEventHistory(
  executionId: string | undefined,
  enabled: boolean
): {
  stepLog: StepLogEntry[];
  truncated: boolean;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
} {
  const query = useQuery({
    queryKey: ['execution-event-history', executionId],
    queryFn: () => fetchAllEvents(executionId as string),
    enabled: enabled && !!executionId,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false
  });

  const stepLog = useMemo(
    () => foldEventsToStepLog(query.data?.items ?? []),
    [query.data?.items]
  );

  return {
    stepLog,
    truncated: query.data?.truncated ?? false,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error
  };
}
