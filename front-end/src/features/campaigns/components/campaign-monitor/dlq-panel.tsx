'use client';

import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ExternalLink,
  Loader2,
  RefreshCw,
  Trash2,
  XCircle
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type { DlqEntry } from '../../types';
import {
  useBulkRetryDlq,
  useCloseDlqEntry,
  useDismissDlqEntry,
  useDlqEntries,
  useDlqSummary,
  useRetryDlqEntry
} from '../../hooks/use-campaigns';
import { MonitorSectionHeader } from './monitor-section-header';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { dlqDisplayMessage } from './dlq-message';
import {
  dlqReplayBlockedReason,
  isDlqEntryReplayable
} from '../../lib/dlq-replayable';
import { DlqEntryDetailDrawer } from './dlq-entry-detail-drawer';

function statusVariant(
  status: string
): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'pending') return 'destructive';
  if (status === 'retrying') return 'default';
  if (status === 'replayed' || status === 'resolved') return 'secondary';
  if (status === 'closed' || status === 'dismissed') return 'outline';
  return 'outline';
}

function statusLabel(status: string, t: (key: string) => string): string {
  if (status === 'pending') return t('monitorDlqStatusPending');
  if (status === 'retrying') return t('monitorDlqStatusRetrying');
  if (status === 'replayed') return t('monitorDlqStatusReplayed');
  if (status === 'closed') return t('monitorDlqStatusClosed');
  if (status === 'resolved') return t('monitorDlqStatusResolved');
  if (status === 'dismissed') return t('monitorDlqStatusDismissed');
  return status;
}

function artifactPreviewUrl(entry: DlqEntry): string | null {
  const refs = entry.artifact_refs ?? {};
  return refs.url ?? refs.screenshot_post ?? refs.screenshot_pre ?? null;
}

function dlqErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } })
      .response?.data?.detail;
    if (
      detail &&
      typeof detail === 'object' &&
      detail !== null &&
      'message' in detail
    ) {
      return String((detail as { message: string }).message);
    }
    if (typeof detail === 'string') return detail;
  }
  return fallback;
}

export function DlqPanel({ campaignId }: { campaignId?: string }) {
  const t = useTranslations('campaignsFeature.list');
  const { canExecute } = useResourcePermissions('executions');
  const { data = [], isLoading } = useDlqEntries(true, 'open', campaignId);
  const { data: summary } = useDlqSummary(true, campaignId);
  const retryMut = useRetryDlqEntry();
  const closeMut = useCloseDlqEntry();
  const dismissMut = useDismissDlqEntry();
  const bulkRetryMut = useBulkRetryDlq();
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null);
  const [closeTarget, setCloseTarget] = useState<DlqEntry | null>(null);
  const [closeReason, setCloseReason] = useState('');
  const [detailEntry, setDetailEntry] = useState<DlqEntry | null>(null);
  const [deviceFilter, setDeviceFilter] = useState('');
  const [errorFilter, setErrorFilter] = useState('');
  const [executionFilter, setExecutionFilter] = useState('');

  const filteredData = useMemo(() => {
    const deviceNeedle = deviceFilter.trim().toLowerCase();
    const errorNeedle = errorFilter.trim().toLowerCase();
    const execNeedle = executionFilter.trim().toLowerCase();
    return data.filter((entry) => {
      if (
        deviceNeedle &&
        !entry.device_serial.toLowerCase().includes(deviceNeedle)
      ) {
        return false;
      }
      if (
        execNeedle &&
        !entry.execution_id.toLowerCase().includes(execNeedle)
      ) {
        return false;
      }
      if (errorNeedle) {
        const msg = dlqDisplayMessage(entry, '').toLowerCase();
        if (!msg.includes(errorNeedle)) return false;
      }
      return true;
    });
  }, [data, deviceFilter, errorFilter, executionFilter]);

  const replayableEntries = useMemo(
    () => filteredData.filter(isDlqEntryReplayable),
    [filteredData]
  );

  const pendingCount = summary?.pending_count ?? data.length;

  const handleRetry = (entry: DlqEntry, fromCheckpoint: boolean) => {
    if (!isDlqEntryReplayable(entry)) return;
    setActiveEntryId(entry.id);
    retryMut.mutate(
      { dlqId: entry.id, fromCheckpoint },
      {
        onSuccess: () => toast.success(t('monitorDlqRetrySuccess')),
        onError: (err) =>
          toast.error(dlqErrorMessage(err, t('monitorDlqRetryFailed'))),
        onSettled: () => setActiveEntryId(null)
      }
    );
  };

  const handleBulkRetry = () => {
    if (replayableEntries.length === 0) return;
    bulkRetryMut.mutate(
      {
        executionIds: replayableEntries.map((e) => e.execution_id),
        fromCheckpoint: true
      },
      {
        onSuccess: (results) => {
          const ok = results.filter(
            (r) => r.status === 'replayed' || r.status === 'resolved'
          ).length;
          toast.success(
            t('monitorDlqBulkRetrySuccess', { ok, total: results.length })
          );
        },
        onError: (err) =>
          toast.error(dlqErrorMessage(err, t('monitorDlqRetryFailed')))
      }
    );
  };

  const submitClose = () => {
    if (!closeTarget || !closeReason.trim()) return;
    closeMut.mutate(
      { dlqId: closeTarget.id, reason: closeReason.trim() },
      {
        onSuccess: () => {
          toast.success(t('monitorDlqCloseSuccess'));
          setCloseTarget(null);
          setCloseReason('');
        },
        onError: (err) =>
          toast.error(dlqErrorMessage(err, t('monitorDlqCloseFailed'))),
        onSettled: () => setActiveEntryId(null)
      }
    );
  };

  return (
    <section className='border-t px-6 py-5'>
      <MonitorSectionHeader
        icon={<AlertTriangle size={20} />}
        title={t('monitorDlqTitle')}
        hint={t('monitorDlqDescription')}
        count={pendingCount}
        countVariant={pendingCount > 0 ? 'destructive' : 'secondary'}
        actions={
          canExecute && replayableEntries.length > 1 ? (
            <Button
              size='sm'
              variant='outline'
              disabled={bulkRetryMut.isPending}
              onClick={handleBulkRetry}
            >
              {bulkRetryMut.isPending ? (
                <Loader2 size={14} className='mr-1 animate-spin' />
              ) : (
                <RefreshCw size={14} className='mr-1' />
              )}
              {t('monitorDlqBulkRetry')}
            </Button>
          ) : null
        }
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
        <div className='mt-4 flex flex-wrap gap-2'>
          <Input
            className='h-8 max-w-[160px] text-xs'
            placeholder={t('monitorDlqFilterDevice')}
            value={deviceFilter}
            onChange={(e) => setDeviceFilter(e.target.value)}
          />
          <Input
            className='h-8 max-w-[160px] text-xs'
            placeholder={t('monitorDlqFilterExecution')}
            value={executionFilter}
            onChange={(e) => setExecutionFilter(e.target.value)}
          />
          <Input
            className='h-8 min-w-[180px] flex-1 text-xs'
            placeholder={t('monitorDlqFilterError')}
            value={errorFilter}
            onChange={(e) => setErrorFilter(e.target.value)}
          />
        </div>
      ) : null}

      {!isLoading && data.length > 0 && filteredData.length === 0 ? (
        <p className='mt-4 text-sm text-muted-foreground'>
          {t('monitorDlqFilterEmpty')}
        </p>
      ) : null}

      {!isLoading && filteredData.length > 0 ? (
        <ul className='mt-4 max-h-[min(55vh,480px)] divide-y overflow-y-auto rounded-lg border bg-muted/20'>
          {filteredData.map((entry) => {
            const isRowPending =
              activeEntryId === entry.id &&
              (retryMut.isPending ||
                dismissMut.isPending ||
                closeMut.isPending);
            const previewUrl = artifactPreviewUrl(entry);
            const reason = dlqDisplayMessage(
              entry,
              t('monitorDlqNoErrorMessage')
            );
            const replayable = isDlqEntryReplayable(entry);
            const blockedReason = dlqReplayBlockedReason(entry, t);

            return (
              <li
                key={entry.id}
                className='flex items-start gap-3 px-4 py-4 first:rounded-t-lg last:rounded-b-lg'
              >
                <button
                  type='button'
                  className='min-w-0 flex-1 space-y-2 text-left'
                  onClick={() => setDetailEntry(entry)}
                >
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
                    {entry.failed_step_id ? (
                      <span className='text-xs text-muted-foreground'>
                        {t('monitorDlqFailedStep', {
                          step: entry.failed_step_id
                        })}
                      </span>
                    ) : null}
                  </div>
                  <p
                    className={cn(
                      'line-clamp-3 text-sm leading-relaxed',
                      reason !== t('monitorDlqNoErrorMessage')
                        ? 'text-foreground/90'
                        : 'italic text-muted-foreground'
                    )}
                    title={reason}
                  >
                    {reason}
                  </p>
                  <div className='flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground'>
                    <span>
                      {t('monitorDlqExecutionShort', {
                        id: entry.execution_id.slice(0, 8)
                      })}
                    </span>
                    {entry.retry_count > 0 ? (
                      <span>
                        {t('monitorDlqRetryCount', {
                          count: entry.retry_count
                        })}
                      </span>
                    ) : null}
                    {previewUrl ? (
                      <a
                        href={previewUrl}
                        target='_blank'
                        rel='noreferrer'
                        className='inline-flex items-center gap-1 text-primary hover:underline'
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t('monitorDlqViewScreenshot')}
                        <ExternalLink size={12} />
                      </a>
                    ) : null}
                  </div>
                </button>

                <div className='flex shrink-0 gap-1'>
                  {canExecute ? (
                    <>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  size='sm'
                                  variant='outline'
                                  className='h-10 gap-1 px-2.5'
                                  disabled={isRowPending || !replayable}
                                >
                                  <RefreshCw
                                    size={16}
                                    className={
                                      isRowPending && retryMut.isPending
                                        ? 'animate-spin'
                                        : undefined
                                    }
                                  />
                                  <ChevronDown
                                    size={14}
                                    className='opacity-60'
                                  />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align='end'>
                                <DropdownMenuItem
                                  onClick={() => handleRetry(entry, true)}
                                >
                                  {t('monitorDlqRetryCheckpoint')}
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onClick={() => handleRetry(entry, false)}
                                >
                                  {t('monitorDlqRetryFull')}
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </span>
                        </TooltipTrigger>
                        {!replayable && blockedReason ? (
                          <TooltipContent className='max-w-xs text-xs'>
                            {blockedReason}
                          </TooltipContent>
                        ) : null}
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            size='icon'
                            variant='outline'
                            className='h-10 w-10'
                            disabled={isRowPending}
                            onClick={() => {
                              setActiveEntryId(entry.id);
                              setCloseTarget(entry);
                              setCloseReason('');
                            }}
                          >
                            <XCircle size={18} />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent className='text-sm'>
                          {t('monitorActionClose')}
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

      <Dialog
        open={closeTarget != null}
        onOpenChange={(open) => {
          if (!open) {
            setCloseTarget(null);
            setCloseReason('');
            setActiveEntryId(null);
          }
        }}
      >
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>{t('monitorDlqCloseTitle')}</DialogTitle>
          </DialogHeader>
          <div className='space-y-2 py-2'>
            <Label htmlFor='dlq-close-reason'>
              {t('monitorDlqCloseReasonLabel')}
            </Label>
            <Input
              id='dlq-close-reason'
              value={closeReason}
              onChange={(e) => setCloseReason(e.target.value)}
              placeholder={t('monitorDlqCloseReasonPlaceholder')}
            />
          </div>
          <DialogFooter>
            <Button variant='outline' onClick={() => setCloseTarget(null)}>
              {t('monitorDlqCloseCancel')}
            </Button>
            <Button
              disabled={!closeReason.trim() || closeMut.isPending}
              onClick={submitClose}
            >
              {closeMut.isPending ? (
                <Loader2 size={16} className='mr-1 animate-spin' />
              ) : null}
              {t('monitorActionClose')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DlqEntryDetailDrawer
        entry={detailEntry}
        open={detailEntry != null}
        onOpenChange={(open) => {
          if (!open) setDetailEntry(null);
        }}
      />
    </section>
  );
}
