'use client';

import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import {
  Activity,
  CalendarClock,
  Clock3,
  History,
  Pencil,
  Play,
  Power,
  Target,
  Timer,
  Trash2
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useConfirm } from '@/providers/modal-provider';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import type { ScheduleOut } from '../services/api';
import {
  useDeleteSchedule,
  useRunNowSchedule,
  useScheduleRuns,
  useToggleSchedule
} from '../hooks/use-schedules';
import { cronExpressionToHumanReadable } from './cron-builder';
import { ScheduleFormDialog } from './schedule-form-dialog';
import { ScheduleRunHistoryDialog } from './schedule-run-history-dialog';

function runStatusLabel(status: string, t: (key: string) => string) {
  const normalized = status.toLowerCase();
  if (['pending', 'queued', 'running'].includes(normalized)) {
    return t('statusRunning');
  }
  if (['success', 'succeeded', 'completed', 'done'].includes(normalized)) {
    return t('statusCompleted');
  }
  if (['failed', 'error', 'cancelled', 'canceled'].includes(normalized)) {
    return t('statusFailed');
  }
  return status;
}

export function ScheduleDetailPanel({
  schedule,
  targetLabel,
  onDeleted
}: {
  schedule: ScheduleOut | null;
  targetLabel: string | null;
  onDeleted: () => void;
}) {
  const t = useTranslations('schedulesFeature.list');
  const tActions = useTranslations('schedulesFeature.actions');
  const tCron = useTranslations('schedulesFeature.cronBuilder');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const dateLocale = locale === 'vi' ? vi : enUS;
  const confirm = useConfirm();
  const perms = useResourcePermissions('schedules');
  const [editOpen, setEditOpen] = useState(false);
  const runNowMutation = useRunNowSchedule();
  const toggleMutation = useToggleSchedule();
  const deleteMutation = useDeleteSchedule();
  const { data: runs = [], isLoading: runsLoading } = useScheduleRuns(
    schedule?.id,
    Boolean(schedule?.id)
  );

  if (!schedule) {
    return (
      <aside className='rounded-xl border bg-card p-5 text-sm text-muted-foreground shadow-sm'>
        <div className='flex size-10 items-center justify-center rounded-lg border bg-background'>
          <CalendarClock className='size-5' />
        </div>
        <h3 className='mt-4 font-semibold text-foreground'>
          {t('detailEmptyTitle')}
        </h3>
        <p className='mt-1 leading-6'>{t('detailEmptyDescription')}</p>
      </aside>
    );
  }

  const frequency = schedule.cron_expression
    ? cronExpressionToHumanReadable(schedule.cron_expression, tCron)
    : '-';
  const nextRun = schedule.next_run_at
    ? formatDistanceToNow(new Date(schedule.next_run_at), {
        addSuffix: true,
        locale: dateLocale
      })
    : t('feedbackNoNextRun');
  const latestRuns = runs.slice(0, 3);
  const isPending =
    runNowMutation.isPending ||
    toggleMutation.isPending ||
    deleteMutation.isPending;

  const handleRunNow = () => {
    runNowMutation.mutate(schedule.id, {
      onSuccess: () => toast.success(tActions('runNowSuccess')),
      onError: (err: unknown) =>
        toast.error(formatFarmApiError(err, tActions('runNowFailed')))
    });
  };

  const handleToggle = () => {
    toggleMutation.mutate(
      { scheduleId: schedule.id, enabled: !schedule.is_enabled },
      {
        onError: (err: unknown) =>
          toast.error(formatFarmApiError(err, tActions('toggleFailed')))
      }
    );
  };

  const handleDelete = () => {
    void (async () => {
      const ok = await confirm({
        title: tActions('deleteConfirmTitle', { name: schedule.name }),
        description: tActions('deleteConfirmDescription'),
        confirmText: tActions('deleteConfirmAction'),
        cancelText: tCommon('cancel'),
        confirmVariant: 'destructive',
        zIndex: 10_000
      });
      if (!ok) return;
      deleteMutation.mutate(schedule.id, {
        onSuccess: () => {
          toast.success(tActions('deleteSuccess', { name: schedule.name }));
          onDeleted();
        },
        onError: (err: unknown) =>
          toast.error(formatFarmApiError(err, tActions('deleteFailed')))
      });
    })();
  };

  return (
    <aside className='overflow-hidden bg-card'>
      <div className='space-y-4 p-4'>
        <div className='rounded-xl border bg-muted/20 p-3'>
          <div className='flex items-start justify-between gap-3'>
            <div className='flex min-w-0 items-start gap-3'>
              <span className='flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background text-primary'>
                <Activity className='size-4' />
              </span>
              <div className='min-w-0'>
                <p className='text-xs font-medium text-muted-foreground'>
                  {t('detailTitle')}
                </p>
                <h3 className='mt-1 truncate text-lg font-semibold tracking-tight text-foreground'>
                  {schedule.name}
                </h3>
              </div>
            </div>
            <Badge
              variant={schedule.is_enabled ? 'default' : 'secondary'}
              className='shrink-0'
            >
              {schedule.is_enabled ? t('enabledOn') : t('enabledOff')}
            </Badge>
          </div>
          {schedule.description ? (
            <p className='mt-3 max-h-20 overflow-hidden text-sm leading-6 text-muted-foreground'>
              {schedule.description}
            </p>
          ) : null}
        </div>

        <div className='grid gap-2 text-sm'>
          <div className='rounded-xl border bg-background p-3 shadow-sm'>
            <div className='flex items-center gap-2 text-xs text-muted-foreground'>
              <Target className='size-3.5' />
              {t('summaryTarget')}
            </div>
            <p className='mt-1.5 truncate font-medium text-foreground'>
              {targetLabel ?? t('targetFleet')}
            </p>
          </div>
          <div className='grid grid-cols-2 gap-2'>
            <div className='rounded-xl border bg-background p-3 shadow-sm'>
              <div className='flex items-center gap-2 text-xs text-muted-foreground'>
                <Timer className='size-3.5' />
                {t('summaryFrequency')}
              </div>
              <p className='mt-1.5 font-medium leading-5 text-foreground'>
                {frequency}
              </p>
            </div>
            <div className='rounded-xl border bg-background p-3 shadow-sm'>
              <div className='flex items-center gap-2 text-xs text-muted-foreground'>
                <CalendarClock className='size-3.5' />
                {t('feedbackNextRunLabel')}
              </div>
              <p className='mt-1.5 font-medium leading-5 text-foreground'>
                {nextRun}
              </p>
            </div>
          </div>
        </div>

        <div className='grid gap-2 rounded-xl border bg-background p-2 shadow-sm'>
          {perms.canExecute ? (
            <Button
              className='h-10 justify-start'
              onClick={handleRunNow}
              disabled={runNowMutation.isPending}
            >
              <Play className='mr-2 size-4' />
              {tActions('runNow')}
            </Button>
          ) : null}
          <div className='grid grid-cols-2 gap-2'>
            {perms.canUpdate ? (
              <Button
                variant='ghost'
                className='justify-start'
                onClick={() => setEditOpen(true)}
                disabled={isPending}
              >
                <Pencil className='mr-2 size-4' />
                {tActions('edit')}
              </Button>
            ) : null}
            {perms.canUpdate ? (
              <Button
                variant='ghost'
                className='justify-start'
                onClick={handleToggle}
                disabled={isPending}
              >
                <Power className='mr-2 size-4' />
                {schedule.is_enabled
                  ? tActions('disableShort')
                  : tActions('enableShort')}
              </Button>
            ) : null}
          </div>
          <div className='grid grid-cols-2 gap-2'>
            <ScheduleRunHistoryDialog
              scheduleId={schedule.id}
              scheduleName={schedule.name}
              trigger={
                <Button
                  variant='ghost'
                  className='justify-start'
                  disabled={isPending}
                >
                  <History className='mr-2 size-4' />
                  {tActions('history')}
                </Button>
              }
            />
            {perms.canDelete ? (
              <Button
                variant='ghost'
                className='justify-start text-destructive hover:text-destructive'
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
              >
                <Trash2 className='mr-2 size-4' />
                {tActions('delete')}
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <Separator />

      <div className='space-y-3 bg-muted/10 p-4'>
        <div className='flex items-center gap-2 text-sm font-semibold text-foreground'>
          <Clock3 className='size-4 text-muted-foreground' />
          {t('detailRecentRuns')}
        </div>
        {runsLoading ? (
          <p className='text-sm text-muted-foreground'>{t('historyLoading')}</p>
        ) : latestRuns.length ? (
          <div className='space-y-2'>
            {latestRuns.map((run) => (
              <div
                key={run.id}
                className='flex items-center justify-between gap-3 rounded-xl border bg-background px-3 py-2 text-sm shadow-sm'
              >
                <Badge variant='secondary' className='shrink-0 text-[11px]'>
                  {runStatusLabel(run.status, t)}
                </Badge>
                <span className='min-w-0 text-right text-xs text-muted-foreground'>
                  <span className='block truncate'>
                    {t('runDeviceSummary', {
                      succeeded: run.devices_succeeded,
                      total: run.devices_dispatched
                    })}
                  </span>
                  <span className='block truncate'>
                    {run.started_at
                      ? formatDistanceToNow(new Date(run.started_at), {
                          addSuffix: true,
                          locale: dateLocale
                        })
                      : '-'}
                  </span>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className='text-sm text-muted-foreground'>{t('historyEmpty')}</p>
        )}
      </div>

      {editOpen && (
        <ScheduleFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          mode='edit'
          schedule={schedule}
        />
      )}
    </aside>
  );
}
