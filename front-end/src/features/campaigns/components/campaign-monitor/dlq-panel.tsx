'use client';

import { useState } from 'react';
import { AlertTriangle, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import {
  useDismissDlqEntry,
  useDlqEntries,
  useDlqSummary,
  useRetryDlqEntry
} from '../../hooks/use-campaigns';
import { MonitorSectionHeader } from './monitor-section-header';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

function statusVariant(
  status: string
): 'default' | 'secondary' | 'destructive' | 'outline' {
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
  const { canExecute } = useResourcePermissions('executions');
  const { data = [], isLoading } = useDlqEntries(true, 'pending', campaignId);
  const { data: summary } = useDlqSummary(true, campaignId);
  const retryMut = useRetryDlqEntry();
  const dismissMut = useDismissDlqEntry();
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null);
  const pendingCount = summary?.pending_count ?? data.length;

  return (
    <section className='border-t px-6 py-5'>
      <MonitorSectionHeader
        icon={<AlertTriangle size={20} />}
        title={t('monitorDlqTitle')}
        hint={t('monitorDlqDescription')}
        count={pendingCount}
        countVariant={pendingCount > 0 ? 'destructive' : 'secondary'}
      />

      {summary?.alert ? (
        <p className='mt-3 text-sm text-destructive'>
          {t('monitorDlqThresholdAlert', {
            count: summary.pending_count,
            threshold: summary.alert_threshold
          })}
        </p>
      ) : null}

      {summary && summary.dismissed_offline_count > 0 ? (
        <p className='mt-3 text-sm text-amber-600 dark:text-amber-400'>
          {t('monitorDlqAutoDismissed', {
            count: summary.dismissed_offline_count,
            minutes: summary.offline_dismiss_minutes
          })}
        </p>
      ) : null}

      {isLoading ? (
        <p className='mt-4 flex items-center gap-2 text-sm text-muted-foreground'>
          <Loader2 size={16} className='animate-spin' />
          {t('monitorDlqLoading')}
        </p>
      ) : null}

      {!isLoading && data.length === 0 ? (
        <p className='mt-4 text-sm text-muted-foreground'>
          {t('monitorDlqEmpty')}
        </p>
      ) : null}

      {!isLoading && data.length > 0 ? (
        <ul className='mt-4 max-h-[min(55vh,480px)] divide-y overflow-y-auto rounded-lg border bg-muted/20'>
          {data.map((entry) => {
            const isRowPending =
              activeEntryId === entry.id &&
              (retryMut.isPending || dismissMut.isPending);

            return (
              <li
                key={entry.id}
                className='flex items-start gap-3 px-4 py-4 first:rounded-t-lg last:rounded-b-lg'
              >
                <div className='min-w-0 flex-1 space-y-2'>
                  <div className='flex flex-wrap items-center gap-2'>
                    <code
                      className='text-sm font-semibold'
                      title={entry.execution_id}
                    >
                      {entry.device_serial}
                    </code>
                    <Badge
                      variant={statusVariant(entry.status)}
                      className='px-2.5 py-0.5 text-xs'
                    >
                      {statusLabel(entry.status, t)}
                    </Badge>
                  </div>
                  <p
                    className={cn(
                      'line-clamp-3 text-sm leading-relaxed',
                      entry.error
                        ? 'text-foreground/90'
                        : 'text-muted-foreground italic'
                    )}
                    title={entry.error ?? undefined}
                  >
                    {entry.error || t('monitorDlqNoErrorMessage')}
                  </p>
                </div>

                <div className='flex shrink-0 gap-1'>
                  {canExecute ? (
                    <>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            size='icon'
                            variant='outline'
                            className='h-10 w-10'
                            disabled={isRowPending}
                            onClick={() => {
                              setActiveEntryId(entry.id);
                              retryMut.mutate(entry.id, {
                                onSuccess: () =>
                                  toast.success(t('monitorDlqRetrySuccess')),
                                onError: () =>
                                  toast.error(t('monitorDlqRetryFailed')),
                                onSettled: () => setActiveEntryId(null)
                              });
                            }}
                          >
                            <RefreshCw
                              size={18}
                              className={
                                isRowPending && retryMut.isPending
                                  ? 'animate-spin'
                                  : ''
                              }
                            />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent className='text-sm'>
                          {t('monitorActionRetry')}
                        </TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            size='icon'
                            variant='outline'
                            className='h-10 w-10 text-muted-foreground'
                            disabled={isRowPending}
                            onClick={() => {
                              setActiveEntryId(entry.id);
                              dismissMut.mutate(entry.id, {
                                onSuccess: () =>
                                  toast.success(t('monitorDlqDismissSuccess')),
                                onError: () =>
                                  toast.error(t('monitorDlqDismissFailed')),
                                onSettled: () => setActiveEntryId(null)
                              });
                            }}
                          >
                            <Trash2 size={18} />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent className='text-sm'>
                          {t('monitorActionDismiss')}
                        </TooltipContent>
                      </Tooltip>
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
