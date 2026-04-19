'use client';

import { useState } from 'react';
import { AlertTriangle, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  useDismissDlqEntry,
  useDlqEntries,
  useRetryDlqEntry,
} from '../../hooks/use-campaigns';

function fmtDate(value: string | null): string {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleString('vi-VN', { hour12: false });
}

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'pending') return 'destructive';
  if (status === 'retrying') return 'default';
  if (status === 'dismissed') return 'secondary';
  return 'outline';
}

function statusLabel(status: string, t: (key: string) => string): string {
  if (status === 'pending') return t('monitorDlqStatusPending');
  if (status === 'retrying') return t('monitorDlqStatusRetrying');
  if (status === 'dismissed') return t('monitorDlqStatusDismissed');
  return status;
}

export function DlqPanel({ campaignId }: { campaignId?: string }) {
  const t = useTranslations('campaignsFeature.list');
  const { data = [], isLoading } = useDlqEntries(true, 'pending', campaignId);
  const retryMut = useRetryDlqEntry();
  const dismissMut = useDismissDlqEntry();
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null);

  return (
    <div className='border-t bg-red-500/[0.02] p-3'>
      <div className='mb-2 flex items-center gap-2'>
        <AlertTriangle size={14} className='text-red-600 dark:text-red-400' />
        <p className='text-xs font-semibold'>{t('monitorDlqTitle')}</p>
        <Badge variant={data.length > 0 ? 'destructive' : 'secondary'} className='ml-auto'>
          {data.length}
        </Badge>
      </div>

      {isLoading ? (
        <div className='flex items-center gap-2 py-2 text-[11px] text-muted-foreground'>
          <Loader2 size={12} className='animate-spin' />
          {t('monitorDlqLoading')}
        </div>
      ) : null}

      {!isLoading && data.length === 0 ? (
        <p className='py-2 text-[11px] text-muted-foreground'>{t('monitorDlqEmpty')}</p>
      ) : null}

      <div className='max-h-56 space-y-2 overflow-y-auto overscroll-contain py-0.5 pb-3 pr-1'>
        {data.map((entry) => {
          const isRowPending =
            activeEntryId === entry.id && (retryMut.isPending || dismissMut.isPending);

          return (
            <div key={entry.id} className='rounded-md border bg-background p-2'>
              <div className='mb-1 flex items-center gap-2'>
                <code className='truncate text-[10px] font-semibold'>{entry.device_serial}</code>
                <Badge variant={statusVariant(entry.status)}>{statusLabel(entry.status, t)}</Badge>
                <span className='ml-auto text-[10px] text-muted-foreground'>
                  {t('monitorDlqRetryCount', { count: entry.retry_count })}
                </span>
              </div>

              <p
                className={cn(
                  'mb-2 line-clamp-2 text-[11px]',
                  entry.error ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'
                )}
                title={entry.error ?? ''}
              >
                {entry.error || t('monitorDlqNoErrorMessage')}
              </p>

              <div className='mb-2 grid grid-cols-2 gap-2 text-[10px] text-muted-foreground'>
                <span title={entry.execution_id}>
                  {t('monitorDlqExecutionShort', { id: entry.execution_id.slice(0, 8) })}
                </span>
                <span className='text-right'>
                  {t('monitorDlqLastAttempt', { time: fmtDate(entry.last_attempt_at) })}
                </span>
              </div>

              <div className='flex shrink-0 flex-wrap items-center justify-end gap-1.5 border-t border-border/60 pt-2'>
                <Button
                  size='sm'
                  variant='outline'
                  className='h-7 gap-1 px-2 text-[10px]'
                  disabled={isRowPending}
                  onClick={() => {
                    setActiveEntryId(entry.id);
                    retryMut.mutate(entry.id, {
                      onSuccess: () => toast.success(t('monitorDlqRetrySuccess')),
                      onError: () => toast.error(t('monitorDlqRetryFailed')),
                      onSettled: () => setActiveEntryId(null),
                    });
                  }}
                >
                  <RefreshCw size={10} className={isRowPending && retryMut.isPending ? 'animate-spin' : ''} />
                  {t('monitorActionRetry')}
                </Button>
                <Button
                  size='sm'
                  variant='ghost'
                  className='h-7 gap-1 px-2 text-[10px] text-muted-foreground'
                  disabled={isRowPending}
                  onClick={() => {
                    setActiveEntryId(entry.id);
                    dismissMut.mutate(entry.id, {
                      onSuccess: () => toast.success(t('monitorDlqDismissSuccess')),
                      onError: () => toast.error(t('monitorDlqDismissFailed')),
                      onSettled: () => setActiveEntryId(null),
                    });
                  }}
                >
                  <Trash2 size={10} />
                  {t('monitorActionDismiss')}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
