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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
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
  useRetryDlqEntry,
  useCampaignDevices
} from '../../hooks/use-campaigns';
import { MonitorSectionHeader } from './monitor-section-header';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { dlqDisplayMessage, dlqHasExplicitMessage } from './dlq-message';
import {
  humanizeDlqMessage,
  resolveDlqDeviceLabel
} from './dlq-user-message';
import { formatTs } from './dlq-run-summary';
import {
  dlqReplayBlockedReason,
  isDlqEntryReplayable
} from '../../lib/dlq-replayable';
import { DlqEntryDetailDrawer } from './dlq-entry-detail-drawer';
import {
  Z_CAMPAIGN_MONITOR_FLOATING,
  Z_CAMPAIGN_MONITOR_NESTED
} from '@/lib/z-index';

import { dlqStatusLabel, dlqStatusVariant } from './dlq-status';

const DLQ_FILTER_ALL = 'all';

function shortenExecutionId(id: string): string {
  const trimmed = id.trim();
  if (trimmed.length <= 12) return trimmed;
  return `${trimmed.slice(0, 8)}…`;
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

export function DlqPanel({
  campaignId,
  pollAggressive = true
}: {
  campaignId?: string;
  pollAggressive?: boolean;
}) {
  const t = useTranslations('campaignsFeature.list');
  const { canExecute } = useResourcePermissions('executions');
  const { data = [], isLoading } = useDlqEntries(
    true,
    'open',
    campaignId,
    pollAggressive
  );
  const { data: summary } = useDlqSummary(true, campaignId, pollAggressive);
  const { data: campaignDevices = [] } = useCampaignDevices(campaignId ?? '');
  const retryMut = useRetryDlqEntry();
  const closeMut = useCloseDlqEntry();
  const dismissMut = useDismissDlqEntry();
  const bulkRetryMut = useBulkRetryDlq();
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null);
  const [closeTarget, setCloseTarget] = useState<DlqEntry | null>(null);
  const [closeReason, setCloseReason] = useState('');
  const [detailEntry, setDetailEntry] = useState<DlqEntry | null>(null);
  const [deviceFilter, setDeviceFilter] = useState(DLQ_FILTER_ALL);
  const [errorFilter, setErrorFilter] = useState(DLQ_FILTER_ALL);
  const [executionFilter, setExecutionFilter] = useState(DLQ_FILTER_ALL);

  const deviceOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: { value: string; label: string }[] = [];
    for (const entry of data) {
      const serial = entry.device_serial.trim();
      if (!serial || seen.has(serial)) continue;
      seen.add(serial);
      const device = resolveDlqDeviceLabel(serial, campaignDevices, t);
      options.push({ value: serial, label: device.label });
    }
    return options.sort((a, b) => a.label.localeCompare(b.label));
  }, [data, campaignDevices, t]);

  const executionOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: { value: string; label: string }[] = [];
    for (const entry of data) {
      const id = entry.execution_id.trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      options.push({
        value: id,
        label: shortenExecutionId(id)
      });
    }
    return options.sort((a, b) => a.label.localeCompare(b.label));
  }, [data]);

  const errorOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: string[] = [];
    for (const entry of data) {
      const raw = dlqDisplayMessage(entry, '');
      const { summary } = humanizeDlqMessage(raw, t);
      const key = summary.trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      options.push(key);
    }
    return options.sort((a, b) => a.localeCompare(b));
  }, [data, t]);

  const filteredData = useMemo(() => {
    return data.filter((entry) => {
      if (
        deviceFilter !== DLQ_FILTER_ALL &&
        entry.device_serial.trim() !== deviceFilter
      ) {
        return false;
      }
      if (
        executionFilter !== DLQ_FILTER_ALL &&
        entry.execution_id.trim() !== executionFilter
      ) {
        return false;
      }
      if (errorFilter !== DLQ_FILTER_ALL) {
        const raw = dlqDisplayMessage(entry, '');
        const { summary } = humanizeDlqMessage(raw, t);
        if (summary.trim() !== errorFilter) return false;
      }
      return true;
    });
  }, [data, deviceFilter, errorFilter, executionFilter, t]);

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
    <section className='min-w-0 px-4 py-5 sm:px-5'>
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
        <div className='mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3'>
          <div className='min-w-0 space-y-1'>
            <Label className='text-[11px] text-muted-foreground'>
              {t('monitorDlqFilterDevice')}
            </Label>
            <Select value={deviceFilter} onValueChange={setDeviceFilter}>
              <SelectTrigger className='h-8 w-full text-xs'>
                <SelectValue placeholder={t('monitorDlqFilterDevice')} />
              </SelectTrigger>
              <SelectContent style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}>
                <SelectItem value={DLQ_FILTER_ALL}>
                  {t('monitorDlqFilterAll')}
                </SelectItem>
                {deviceOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className='min-w-0 space-y-1'>
            <Label className='text-[11px] text-muted-foreground'>
              {t('monitorDlqFilterExecution')}
            </Label>
            <Select value={executionFilter} onValueChange={setExecutionFilter}>
              <SelectTrigger className='h-8 w-full font-mono text-xs'>
                <SelectValue placeholder={t('monitorDlqFilterExecution')} />
              </SelectTrigger>
              <SelectContent style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}>
                <SelectItem value={DLQ_FILTER_ALL}>
                  {t('monitorDlqFilterAll')}
                </SelectItem>
                {executionOptions.map((option) => (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    title={option.value}
                  >
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className='min-w-0 space-y-1'>
            <Label className='text-[11px] text-muted-foreground'>
              {t('monitorDlqFilterError')}
            </Label>
            <Select value={errorFilter} onValueChange={setErrorFilter}>
              <SelectTrigger className='h-8 w-full text-xs'>
                <SelectValue placeholder={t('monitorDlqFilterError')} />
              </SelectTrigger>
              <SelectContent style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}>
                <SelectItem value={DLQ_FILTER_ALL}>
                  {t('monitorDlqFilterAll')}
                </SelectItem>
                {errorOptions.map((option) => (
                  <SelectItem key={option} value={option} title={option}>
                    <span className='line-clamp-2'>{option}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      ) : null}

      {!isLoading && data.length > 0 && filteredData.length === 0 ? (
        <p className='mt-4 text-sm text-muted-foreground'>
          {t('monitorDlqFilterEmpty')}
        </p>
      ) : null}

      {!isLoading && filteredData.length > 0 ? (
        <ul className='mt-4 max-h-[min(62vh,620px)] divide-y overflow-y-auto rounded-lg border bg-muted/20'>
          {filteredData.map((entry) => {
            const isRowPending =
              activeEntryId === entry.id &&
              (retryMut.isPending ||
                dismissMut.isPending ||
                closeMut.isPending);
            const previewUrl = artifactPreviewUrl(entry);
            const rawMessage = dlqDisplayMessage(
              entry,
              t('monitorDlqNoErrorMessage')
            );
            const { summary: reason, technical } = humanizeDlqMessage(
              rawMessage,
              t
            );
            const hasExplicitMessage =
              dlqHasExplicitMessage(entry) || Boolean(technical);
            const device = resolveDlqDeviceLabel(
              entry.device_serial,
              campaignDevices,
              t
            );
            const replayable = isDlqEntryReplayable(entry);
            const blockedReason = dlqReplayBlockedReason(entry, t);

            return (
              <li
                key={entry.id}
                className='min-w-0 space-y-2 px-3 py-3 first:rounded-t-lg last:rounded-b-lg sm:px-4 sm:py-4'
              >
                <div className='flex min-w-0 items-start justify-between gap-2'>
                  <div className='min-w-0 flex-1 space-y-1'>
                    <span
                      className='block break-all font-mono text-sm font-semibold leading-snug text-foreground'
                      title={device.title}
                    >
                      {device.label}
                    </span>
                    <Badge
                      variant={dlqStatusVariant(entry.status)}
                      className='w-fit px-2.5 py-0.5 text-xs'
                    >
                      {dlqStatusLabel(entry.status, t)}
                    </Badge>
                  </div>
                  <div className='flex shrink-0 items-center gap-1'>
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
                                    className='h-9 gap-1 px-2'
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
                                <DropdownMenuContent
                                  align='end'
                                  style={{
                                    zIndex: Z_CAMPAIGN_MONITOR_FLOATING
                                  }}
                                >
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
                            <TooltipContent
                              className='max-w-xs text-xs'
                              style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}
                            >
                              {blockedReason}
                            </TooltipContent>
                          ) : null}
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size='icon'
                              variant='outline'
                              className='size-9'
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
                          <TooltipContent
                            className='text-sm'
                            style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}
                          >
                            {t('monitorActionClose')}
                          </TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              size='icon'
                              variant='outline'
                              className='size-9 text-muted-foreground'
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
                          <TooltipContent
                            className='text-sm'
                            style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}
                          >
                            {t('monitorActionDismiss')}
                          </TooltipContent>
                        </Tooltip>
                      </>
                    ) : null}
                  </div>
                </div>

                <button
                  type='button'
                  className='block w-full min-w-0 text-left'
                  onClick={() => setDetailEntry(entry)}
                >
                  <p
                    className={cn(
                      'whitespace-pre-wrap break-words text-sm leading-relaxed',
                      hasExplicitMessage
                        ? 'text-foreground/90'
                        : 'italic text-muted-foreground'
                    )}
                    title={technical || reason}
                  >
                    {reason}
                  </p>
                  <div className='mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground'>
                    <span>
                      {t('monitorDlqFailedAt', {
                        time: formatTs(entry.created_at)
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
        <DialogContent
          zIndex={Z_CAMPAIGN_MONITOR_NESTED}
          className='sm:max-w-md'
        >
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
        campaignId={campaignId}
        open={detailEntry != null}
        onOpenChange={(open) => {
          if (!open) setDetailEntry(null);
        }}
      />
    </section>
  );
}
