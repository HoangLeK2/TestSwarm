'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Clock,
  History,
  Loader2,
  MessageSquare,
  Smartphone,
  XCircle
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import {
  useCampaignExecutionHistory,
  useExecutionTaskLog
} from '../hooks/use-campaigns';
import type { CampaignOut, ExecutionOut, ExecutionTaskLogStep } from '../types';
import { useTranslations } from 'next-intl';

type Props = {
  campaign: CampaignOut;
  children?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  initialExecutionId?: string | null;
};

function dateLabel(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'short',
    timeStyle: 'short'
  }).format(d);
}

function deviceLabel(execution?: ExecutionOut | null): string {
  const cfg = (execution?.device_config ?? {}) as Record<string, unknown>;
  const fromConfig = cfg.device_serial;
  return typeof fromConfig === 'string' && fromConfig.trim()
    ? fromConfig.trim()
    : '—';
}

function statusTone(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === 'completed' || normalized === 'success') {
    return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
  }
  if (normalized === 'running' || normalized === 'pending') {
    return 'border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-300';
  }
  if (normalized === 'failed' || normalized === 'error') {
    return 'border-destructive/25 bg-destructive/10 text-destructive';
  }
  return 'border-border bg-muted text-muted-foreground';
}

function statusIcon(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === 'completed' || normalized === 'success') {
    return <CheckCircle2 className='size-3' />;
  }
  if (normalized === 'failed' || normalized === 'error') {
    return <XCircle className='size-3' />;
  }
  return <Clock className='size-3' />;
}

function stepStatusClass(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === 'completed' || normalized === 'success') {
    return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
  }
  if (normalized === 'failed' || normalized === 'error') {
    return 'bg-destructive/10 text-destructive';
  }
  if (normalized === 'running' || normalized === 'in_progress') {
    return 'bg-blue-500/10 text-blue-700 dark:text-blue-300';
  }
  return 'bg-muted text-muted-foreground';
}

function StepRow({
  step,
  fallbackLabel
}: {
  step: ExecutionTaskLogStep;
  fallbackLabel: string;
}) {
  const stepType = step.step_type || fallbackLabel;
  return (
    <div className='grid grid-cols-[3.25rem_minmax(0,1fr)_auto] gap-2 border-b px-3 py-2 last:border-b-0'>
      <span className='font-mono text-[11px] text-muted-foreground'>
        #{step.step_index}
      </span>
      <div className='min-w-0'>
        <p className='truncate text-xs font-medium text-foreground'>
          {stepType}
        </p>
        {step.message ? (
          <p
            className='mt-0.5 line-clamp-2 text-[11px] text-muted-foreground'
            title={step.message}
          >
            {step.message}
          </p>
        ) : null}
      </div>
      <span
        className={cn(
          'h-5 rounded px-1.5 py-0.5 text-[10px] font-medium',
          stepStatusClass(step.status)
        )}
      >
        {step.status}
      </span>
    </div>
  );
}

export function CampaignRunHistoryDialog({
  campaign,
  children,
  open: controlledOpen,
  onOpenChange,
  initialExecutionId
}: Props) {
  const t = useTranslations('campaignsFeature.list');
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = onOpenChange ?? setUncontrolledOpen;
  const history = useCampaignExecutionHistory(campaign.id, open, false);
  const executions = useMemo(() => history.data ?? [], [history.data]);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(
    initialExecutionId ?? null
  );

  useEffect(() => {
    if (!open) return;
    const preferred = initialExecutionId?.trim();
    if (preferred) {
      setSelectedExecutionId(preferred);
      return;
    }
    if (!selectedExecutionId && executions[0]) {
      setSelectedExecutionId(executions[0].id);
    }
  }, [executions, initialExecutionId, open, selectedExecutionId]);

  const selectedExecution = useMemo(
    () => executions.find((execution) => execution.id === selectedExecutionId),
    [executions, selectedExecutionId]
  );
  const taskLog = useExecutionTaskLog(
    selectedExecutionId ?? undefined,
    open,
    false
  );
  const summary = taskLog.data?.summary;
  const counters = summary?.counters ?? {};

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {children ? <DialogTrigger asChild>{children}</DialogTrigger> : null}
      <DialogContent className='flex max-h-[92vh] max-w-6xl flex-col gap-0 overflow-hidden p-0'>
        <DialogHeader className='border-b px-5 py-3'>
          <div className='flex min-w-0 items-center gap-2'>
            <History className='size-4 text-primary' />
            <DialogTitle className='truncate text-sm font-semibold'>
              {t('runHistoryTitle', { campaign: campaign.name })}
            </DialogTitle>
          </div>
          <p className='font-mono text-[10px] text-muted-foreground'>
            {campaign.id}
          </p>
        </DialogHeader>

        <div className='grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[20rem_minmax(0,1fr)]'>
          <div className='min-h-0 border-b md:border-b-0 md:border-r'>
            <div className='flex items-center justify-between border-b px-3 py-2'>
              <p className='text-[11px] font-semibold uppercase tracking-wide text-muted-foreground'>
                {t('runHistoryListTitle')}
              </p>
              {history.isFetching ? (
                <Loader2 className='size-3 animate-spin text-muted-foreground' />
              ) : null}
            </div>
            <ScrollArea className='h-[15rem] md:h-[calc(92vh-7rem)]'>
              {history.isError ? (
                <p className='px-3 py-4 text-xs text-destructive'>
                  {formatFarmApiError(history.error, t('runHistoryLoadFailed'))}
                </p>
              ) : history.isLoading ? (
                <p className='px-3 py-4 text-xs text-muted-foreground'>
                  {t('runHistoryLoading')}
                </p>
              ) : executions.length === 0 ? (
                <p className='px-3 py-4 text-xs text-muted-foreground'>
                  {t('runHistoryEmpty')}
                </p>
              ) : (
                executions.map((execution) => {
                  const active = execution.id === selectedExecutionId;
                  return (
                    <button
                      key={execution.id}
                      type='button'
                      className={cn(
                        'flex w-full flex-col gap-1 border-b px-3 py-2 text-left transition-colors hover:bg-muted/60',
                        active && 'bg-primary/5'
                      )}
                      onClick={() => setSelectedExecutionId(execution.id)}
                    >
                      <div className='flex min-w-0 items-center gap-2'>
                        <Badge
                          variant='outline'
                          className={cn(
                            'h-5 max-w-[8rem] truncate px-1.5 text-[10px]',
                            statusTone(execution.status)
                          )}
                        >
                          {statusIcon(execution.status)}
                          {execution.status}
                        </Badge>
                        <span className='min-w-0 truncate font-mono text-[10px] text-muted-foreground'>
                          {execution.id.slice(0, 8)}
                        </span>
                      </div>
                      <div className='flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground'>
                        <Smartphone className='size-3 shrink-0' />
                        <span className='truncate'>
                          {deviceLabel(execution)}
                        </span>
                      </div>
                      <p className='text-[10px] text-muted-foreground'>
                        {dateLabel(
                          execution.started_at ??
                            execution.created_at ??
                            execution.finished_at
                        )}
                      </p>
                    </button>
                  );
                })
              )}
            </ScrollArea>
          </div>

          <div className='min-h-0'>
            {!selectedExecutionId ? (
              <p className='px-5 py-8 text-sm text-muted-foreground'>
                {t('runHistorySelectRun')}
              </p>
            ) : (
              <div className='flex h-full min-h-0 flex-col'>
                <div className='border-b px-5 py-3'>
                  <div className='flex min-w-0 flex-wrap items-center gap-2'>
                    <Badge
                      variant='outline'
                      className={cn(
                        'h-6 px-2 text-[11px]',
                        statusTone(
                          taskLog.data?.status ??
                            selectedExecution?.status ??
                            ''
                        )
                      )}
                    >
                      {statusIcon(
                        taskLog.data?.status ?? selectedExecution?.status ?? ''
                      )}
                      {taskLog.data?.status ?? selectedExecution?.status ?? '—'}
                    </Badge>
                    <span className='font-mono text-[11px] text-muted-foreground'>
                      {selectedExecutionId}
                    </span>
                  </div>
                  <div className='mt-2 grid gap-2 text-[11px] text-muted-foreground sm:grid-cols-2 lg:grid-cols-4'>
                    <span>
                      {t('monitorTaskLogDevice')}:{' '}
                      <b className='font-medium text-foreground'>
                        {taskLog.data?.context.device_serial ??
                          deviceLabel(selectedExecution)}
                      </b>
                    </span>
                    <span>
                      {t('monitorTaskLogAccount')}:{' '}
                      <b className='font-medium text-foreground'>
                        {taskLog.data?.context.account_label ??
                          selectedExecution?.account_id ??
                          '—'}
                      </b>
                    </span>
                    <span>
                      {t('runHistoryStarted')}:{' '}
                      <b className='font-medium text-foreground'>
                        {dateLabel(
                          taskLog.data?.started_at ??
                            selectedExecution?.started_at
                        )}
                      </b>
                    </span>
                    <span>
                      {t('runHistoryFinished')}:{' '}
                      <b className='font-medium text-foreground'>
                        {dateLabel(
                          taskLog.data?.finished_at ??
                            selectedExecution?.finished_at
                        )}
                      </b>
                    </span>
                  </div>
                </div>

                <div className='grid grid-cols-2 gap-2 border-b px-5 py-3 sm:grid-cols-4'>
                  {(['completed', 'running', 'failed', 'total'] as const).map(
                    (key) => {
                      const value =
                        key === 'completed'
                          ? summary?.completed_steps
                          : key === 'running'
                            ? summary?.running_steps
                            : key === 'failed'
                              ? summary?.failed_steps
                              : summary?.total_steps;
                      return (
                        <div key={key} className='rounded-md border px-3 py-2'>
                          <p className='text-[10px] text-muted-foreground'>
                            {t(`runHistorySummary.${key}`)}
                          </p>
                          <p className='text-sm font-semibold text-foreground'>
                            {(value ?? 0).toLocaleString()}
                          </p>
                        </div>
                      );
                    }
                  )}
                </div>

                <div className='flex flex-wrap gap-1.5 border-b px-5 py-2 text-[10px]'>
                  {(['matched', 'liked', 'commented', 'skipped'] as const).map(
                    (key) => (
                      <span
                        key={key}
                        className='inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-muted-foreground'
                      >
                        {key === 'commented' ? (
                          <MessageSquare className='size-3' />
                        ) : null}
                        {t(`monitorTaskLogCounter.${key}`)}:{' '}
                        <b className='font-semibold text-foreground'>
                          {Number(counters[key] ?? 0)}
                        </b>
                      </span>
                    )
                  )}
                </div>

                <ScrollArea className='min-h-0 flex-1'>
                  {taskLog.isError ? (
                    <p className='px-5 py-5 text-xs text-destructive'>
                      {formatFarmApiError(
                        taskLog.error,
                        t('monitorTaskLogFailedToLoad')
                      )}
                    </p>
                  ) : taskLog.isLoading ? (
                    <p className='px-5 py-5 text-xs text-muted-foreground'>
                      {t('monitorTaskLogLoading')}
                    </p>
                  ) : !taskLog.data?.steps.length ? (
                    <p className='px-5 py-5 text-xs text-muted-foreground'>
                      {t('monitorTaskLogEmpty')}
                    </p>
                  ) : (
                    <div>
                      {taskLog.data.steps.map((step) => (
                        <StepRow
                          key={step.id}
                          step={step}
                          fallbackLabel={t('monitorStepsHeading')}
                        />
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
