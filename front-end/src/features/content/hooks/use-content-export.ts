'use client';

import { useCallback, useState } from 'react';
import {
  appendExportJob,
  updateExportJob,
  type ContentExportJobRecord
} from '../lib/export-history';
import {
  contentApi,
  type ContentFilters,
  type ExportFormat
} from '../services/api';
import { triggerBlobDownload } from '../lib/download';

function newJobId(): string {
  return `exp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function useContentExport() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const runExport = useCallback(
    async (
      filters: ContentFilters,
      format: ExportFormat,
      opts?: { itemCount?: number; createdBy?: string | null }
    ): Promise<ContentExportJobRecord> => {
      const id = newJobId();
      const queued: ContentExportJobRecord = {
        id,
        status: 'queued',
        format,
        filterSnapshot: { ...filters },
        itemCountEstimate: opts?.itemCount ?? null,
        createdAt: new Date().toISOString(),
        createdBy: opts?.createdBy ?? null
      };
      appendExportJob(queued);
      setActiveJobId(id);
      setIsExporting(true);
      updateExportJob(id, { status: 'running' });

      try {
        const { blob, filename } = await contentApi.exportStream(
          filters,
          format
        );
        triggerBlobDownload(blob, filename);
        const completed: Partial<ContentExportJobRecord> = {
          status: 'completed',
          completedAt: new Date().toISOString(),
          filename
        };
        updateExportJob(id, completed);
        return { ...queued, ...completed, status: 'completed' };
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Export failed';
        updateExportJob(id, {
          status: 'failed',
          completedAt: new Date().toISOString(),
          error: message
        });
        throw err;
      } finally {
        setIsExporting(false);
        setActiveJobId(null);
      }
    },
    []
  );

  const retryExport = useCallback(
    async (job: ContentExportJobRecord) => {
      return runExport(job.filterSnapshot, job.format, {
        itemCount: job.itemCountEstimate ?? undefined,
        createdBy: job.createdBy
      });
    },
    [runExport]
  );

  return { runExport, retryExport, isExporting, activeJobId };
}
