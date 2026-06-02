'use client';

import { useCallback, useEffect, useState } from 'react';
import { Download, FileSpreadsheet, Loader2, RefreshCw } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Can } from '@/features/auth';
import { useAuthContext } from '@/features/auth/providers/auth-provider';
import type { ContentFilters, ExportFormat } from '../services/api';
import { useContentExport } from '../hooks/use-content-export';
import {
  getExportJob,
  listExportHistory,
  type ContentExportJobRecord
} from '../lib/export-history';
import { triggerBlobDownload } from '../lib/download';
import { contentApi } from '../services/api';

function statusVariant(
  status: ContentExportJobRecord['status']
): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'secondary';
  if (status === 'failed') return 'destructive';
  if (status === 'running' || status === 'queued') return 'default';
  return 'outline';
}

function filterSummary(filters: ContentFilters): string {
  const parts: string[] = [];
  if (filters.collection) parts.push(`collection=${filters.collection}`);
  if (filters.platform) parts.push(`platform=${filters.platform}`);
  if (filters.campaign_id) parts.push(`campaign=${filters.campaign_id.slice(0, 8)}…`);
  if (filters.run_id) parts.push(`execution=${filters.run_id.slice(0, 8)}…`);
  if (filters.search) parts.push(`search="${filters.search}"`);
  return parts.length ? parts.join(' · ') : '—';
}

type ExportDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: ContentFilters;
  itemCount: number;
  onExported?: () => void;
};

export function ContentExportDialog({
  open,
  onOpenChange,
  filters,
  itemCount,
  onExported
}: ExportDialogProps) {
  const t = useTranslations('contentFeature.export');
  const { user } = useAuthContext();
  const { runExport, isExporting } = useContentExport();
  const [format, setFormat] = useState<ExportFormat>('csv');

  const handleExport = async () => {
    if (itemCount === 0) {
      toast.error(t('emptyCollection'));
      return;
    }
    try {
      await runExport(filters, format, {
        itemCount,
        createdBy: user?.email ?? user?.givenName ?? null
      });
      toast.success(t('exportSuccess'));
      onExported?.();
      onOpenChange(false);
    } catch {
      toast.error(t('exportFailed'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('dialogTitle')}</DialogTitle>
        </DialogHeader>
        <div className='space-y-3 text-sm'>
          <p className='text-muted-foreground'>{t('dialogHint')}</p>
          <div className='rounded-md border bg-muted/30 px-3 py-2 text-xs'>
            <p className='font-medium'>{t('filterSnapshot')}</p>
            <p className='mt-1 text-muted-foreground'>{filterSummary(filters)}</p>
            <p className='mt-1 text-muted-foreground'>
              {t('itemEstimate', { count: itemCount })}
            </p>
          </div>
          <div className='flex gap-2'>
            {(['csv', 'xlsx'] as ExportFormat[]).map((f) => (
              <Button
                key={f}
                type='button'
                size='sm'
                variant={format === f ? 'default' : 'outline'}
                onClick={() => setFormat(f)}
              >
                {f.toUpperCase()}
              </Button>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            {t('cancel')}
          </Button>
          <Can
            object='content'
            action='read'
            fallback={
              <Button disabled>{t('noPermission')}</Button>
            }
          >
            <Button disabled={isExporting} onClick={() => void handleExport()}>
              {isExporting ? (
                <Loader2 className='mr-1.5 size-4 animate-spin' />
              ) : (
                <Download className='mr-1.5 size-4' />
              )}
              {t('startExport')}
            </Button>
          </Can>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ContentExportHistoryPanel() {
  const t = useTranslations('contentFeature.export');
  const [records, setRecords] = useState<ContentExportJobRecord[]>([]);
  const { retryExport, isExporting } = useContentExport();

  const refresh = useCallback(() => {
    setRecords(listExportHistory());
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleRetry = async (job: ContentExportJobRecord) => {
    try {
      await retryExport(job);
      toast.success(t('exportSuccess'));
      refresh();
    } catch {
      toast.error(t('exportFailed'));
    }
  };

  const handleRedownload = async (job: ContentExportJobRecord) => {
    if (job.status !== 'completed') return;
    try {
      const { blob, filename } = await contentApi.exportStream(
        job.filterSnapshot,
        job.format
      );
      triggerBlobDownload(blob, filename);
    } catch {
      toast.error(t('downloadExpired'));
    }
  };

  return (
    <Card>
      <CardHeader className='flex flex-row items-center justify-between gap-2 space-y-0'>
        <div>
          <CardTitle className='text-base'>{t('historyTitle')}</CardTitle>
          <p className='text-xs text-muted-foreground'>{t('historyHint')}</p>
        </div>
        <Button variant='ghost' size='icon' className='size-8' onClick={refresh}>
          <RefreshCw className='size-4' />
        </Button>
      </CardHeader>
      <CardContent>
        {records.length === 0 ? (
          <p className='text-sm text-muted-foreground'>{t('historyEmpty')}</p>
        ) : (
          <ul className='divide-y rounded-md border'>
            {records.map((job) => (
              <li key={job.id} className='flex flex-wrap items-center gap-2 px-3 py-3 text-xs'>
                <FileSpreadsheet className='size-4 shrink-0 text-muted-foreground' />
                <div className='min-w-0 flex-1'>
                  <p className='font-medium uppercase'>{job.format}</p>
                  <p className='truncate text-muted-foreground'>
                    {filterSummary(job.filterSnapshot)}
                  </p>
                  {job.error ? (
                    <p className='mt-0.5 text-destructive'>{job.error}</p>
                  ) : null}
                </div>
                <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
                {job.status === 'failed' ? (
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-7'
                    disabled={isExporting}
                    onClick={() => void handleRetry(job)}
                  >
                    {t('retry')}
                  </Button>
                ) : null}
                {job.status === 'completed' ? (
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-7'
                    onClick={() => void handleRedownload(job)}
                  >
                    {t('downloadAgain')}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function ContentExportJobDetailGuard({ jobId }: { jobId: string }) {
  const t = useTranslations('contentFeature.export');
  const job = getExportJob(jobId);

  if (!job) {
    return (
      <p className='text-sm text-muted-foreground'>{t('jobNotFound')}</p>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>{t('jobDetailTitle')}</CardTitle>
      </CardHeader>
      <CardContent className='space-y-2 text-sm'>
        <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
        <p>{filterSummary(job.filterSnapshot)}</p>
        {job.error ? <p className='text-destructive'>{job.error}</p> : null}
      </CardContent>
    </Card>
  );
}
