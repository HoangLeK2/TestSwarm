'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { enUS, vi } from 'date-fns/locale';
import { ChevronLeft, History } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { useScheduleRun, useScheduleRuns } from '../hooks/use-schedules';
import { ScheduleRunDetailPanel } from './schedule-run-detail-panel';
import { ScheduleRunStatusBadge } from './schedule-run-display';
import { ScheduleRunHistoryList } from './schedule-run-history-list';
import { cn } from '@/lib/utils';

export function ScheduleRunHistoryDialog({
  scheduleId,
  scheduleName,
  trigger,
  open: controlledOpen,
  onOpenChange
}: {
  scheduleId: string;
  scheduleName: string;
  trigger?: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations('schedulesFeature.list');
  const locale = useLocale();
  const dateLocale = locale === 'vi' ? vi : enUS;
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = onOpenChange ?? setUncontrolledOpen;
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);

  const {
    data: runs = [],
    isLoading,
    isFetching,
    error: runsError,
    refetch: refetchRuns
  } = useScheduleRuns(scheduleId, open);
  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedRunId) ?? null,
    [runs, selectedRunId]
  );
  const {
    data: runDetail,
    isLoading: isDetailLoading,
    error: detailError,
    refetch: refetchDetail
  } = useScheduleRun(scheduleId, selectedRunId);

  useEffect(() => {
    if (!open || !runs.length) return;
    if (!selectedRunId || !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(runs[0].id);
    }
  }, [open, runs, selectedRunId]);

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setSelectedRunId(null);
      setMobileDetailOpen(false);
    }
  };

  const handleSelectRun = (runId: string) => {
    setSelectedRunId(runId);
    setMobileDetailOpen(true);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      {trigger ? (
        <DialogTrigger asChild>{trigger}</DialogTrigger>
      ) : controlledOpen === undefined ? (
        <DialogTrigger asChild>
          <Button
            size='sm'
            variant='ghost'
            className='h-7 gap-1 px-2 text-xs'
            title={t('history')}
            aria-label={t('history')}
          >
            <History size={14} aria-hidden />
            <span>{t('history')}</span>
          </Button>
        </DialogTrigger>
      ) : null}

      <DialogContent className='flex h-[calc(100vh-2rem)] max-h-[50rem] w-[calc(100vw-2rem)] !max-w-6xl flex-col gap-0 overflow-hidden !p-0'>
        <DialogHeader className='shrink-0 border-b px-5 py-4 pr-12 md:px-6 md:py-5'>
          <div className='flex items-start gap-3'>
            <span className='rounded-lg bg-muted p-2 text-muted-foreground'>
              <History className='size-5' aria-hidden />
            </span>
            <div className='min-w-0 flex-1'>
              <div className='flex flex-wrap items-center gap-2'>
                <DialogTitle className='truncate text-base md:text-lg'>
                  {t('historyTitle', { name: scheduleName })}
                </DialogTitle>
                {runs[0] ? (
                  <ScheduleRunStatusBadge status={runs[0].status} />
                ) : null}
              </div>
              <DialogDescription className='mt-1'>
                {runs.length
                  ? t('historyDescription', { count: runs.length })
                  : t('historyDescriptionEmpty')}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className='flex min-h-0 flex-1 flex-col md:grid md:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.2fr)] md:grid-rows-1'>
          <section
            className={cn(
              'min-h-0 flex-1 flex-col border-b bg-muted/20 md:flex md:border-b-0 md:border-r',
              mobileDetailOpen ? 'hidden' : 'flex'
            )}
          >
            <div className='flex items-center justify-between border-b px-4 py-3'>
              <h2 className='text-sm font-semibold'>{t('recentRuns')}</h2>
              {runs.length ? (
                <span className='text-xs text-muted-foreground'>
                  {t('runCount', { count: runs.length })}
                </span>
              ) : null}
            </div>
            <ScheduleRunHistoryList
              runs={runs}
              selectedRunId={selectedRunId}
              isLoading={isLoading}
              isFetching={isFetching}
              error={runsError}
              dateLocale={dateLocale}
              onSelect={handleSelectRun}
              onRetry={() => void refetchRuns()}
            />
          </section>

          <section
            className={cn(
              'min-h-0 flex-1 flex-col bg-background md:flex',
              mobileDetailOpen ? 'flex' : 'hidden'
            )}
          >
            <div className='flex items-center gap-2 border-b px-3 py-2 md:px-5 md:py-3'>
              <Button
                size='icon'
                variant='ghost'
                className='size-8 md:hidden'
                aria-label={t('backToRuns')}
                onClick={() => setMobileDetailOpen(false)}
              >
                <ChevronLeft className='size-4' aria-hidden />
              </Button>
              <h2 className='text-sm font-semibold'>{t('runDetails')}</h2>
            </div>
            <ScheduleRunDetailPanel
              run={runDetail ?? selectedRun}
              isLoading={!!selectedRunId && isDetailLoading && !selectedRun}
              error={detailError}
              dateLocale={dateLocale}
              onRetry={() => void refetchDetail()}
            />
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
