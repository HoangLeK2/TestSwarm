'use client';

import { useEffect, useMemo, useState } from 'react';
import { format, formatDistanceToNow } from 'date-fns';
import type { Locale } from 'date-fns';
import { AlertCircle, History, RefreshCw, Smartphone } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import { cn } from '@/lib/utils';
import type { ScheduleRunOut } from '../services/api';
import { ScheduleRunStatusBadge } from './schedule-run-display';

function RunListSkeleton() {
  const t = useTranslations('schedulesFeature.list');
  return (
    <div
      className='space-y-2 p-3'
      aria-busy='true'
      aria-label={t('historyLoading')}
    >
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className='space-y-3 rounded-lg border p-4'>
          <div className='flex items-center justify-between gap-3'>
            <Skeleton className='h-5 w-24' />
            <Skeleton className='h-4 w-20' />
          </div>
          <Skeleton className='h-4 w-4/5' />
        </div>
      ))}
    </div>
  );
}

export function ScheduleRunHistoryList({
  runs,
  selectedRunId,
  isLoading,
  isFetching,
  error,
  dateLocale,
  onSelect,
  onRetry
}: {
  runs: ScheduleRunOut[];
  selectedRunId: string | null;
  isLoading: boolean;
  isFetching: boolean;
  error: unknown;
  dateLocale: Locale;
  onSelect: (runId: string) => void;
  onRetry: () => void;
}) {
  const t = useTranslations('schedulesFeature.list');
  const pageSize = 8;
  const pageCount = Math.max(1, Math.ceil(runs.length / pageSize));
  const [pageIndex, setPageIndex] = useState(0);
  const visibleRuns = useMemo(
    () => runs.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize),
    [pageIndex, runs]
  );

  useEffect(() => {
    if (pageIndex >= pageCount) setPageIndex(pageCount - 1);
  }, [pageCount, pageIndex]);

  if (isLoading) return <RunListSkeleton />;

  if (error) {
    return (
      <div className='p-4'>
        <Alert variant='destructive'>
          <AlertCircle aria-hidden />
          <AlertTitle>{t('historyErrorTitle')}</AlertTitle>
          <AlertDescription>
            <p>{t('historyErrorDescription')}</p>
            <Button
              size='sm'
              variant='outline'
              className='mt-2'
              onClick={onRetry}
            >
              <RefreshCw className='size-3.5' aria-hidden />
              {t('retry')}
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!runs.length) {
    return (
      <div className='flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center'>
        <span className='mb-4 rounded-full bg-muted p-3 text-muted-foreground'>
          <History className='size-5' aria-hidden />
        </span>
        <p className='font-medium text-foreground'>{t('historyEmpty')}</p>
        <p className='mt-1 max-w-xs text-sm text-muted-foreground'>
          {t('historyEmptyDescription')}
        </p>
      </div>
    );
  }

  return (
    <div className='relative flex min-h-0 flex-1 flex-col'>
      {isFetching ? (
        <div className='absolute right-3 top-3 z-10 rounded-full border bg-background p-1.5 text-muted-foreground shadow-sm'>
          <RefreshCw
            className='size-3.5 animate-spin'
            aria-label={t('refreshing')}
          />
        </div>
      ) : null}
      <ScrollArea className='min-h-0 flex-1'>
        <div
          className='space-y-2 p-3'
          role='list'
          aria-label={t('runListLabel')}
        >
          {visibleRuns.map((run) => {
            const selected = run.id === selectedRunId;
            return (
              <div key={run.id} role='listitem'>
                <Button
                  type='button'
                  variant='ghost'
                  className={cn(
                    'h-auto w-full flex-col items-stretch gap-3 rounded-lg border px-4 py-3 text-left hover:bg-muted/50',
                    selected
                      ? 'border-primary/40 bg-primary/5 shadow-sm hover:bg-primary/5'
                      : 'border-transparent bg-background'
                  )}
                  aria-pressed={selected}
                  onClick={() => onSelect(run.id)}
                >
                  <span className='flex items-start justify-between gap-3'>
                    <ScheduleRunStatusBadge status={run.status} />
                    <span className='text-xs font-normal text-muted-foreground'>
                      {formatDistanceToNow(new Date(run.started_at), {
                        addSuffix: true,
                        locale: dateLocale
                      })}
                    </span>
                  </span>
                  <span className='flex items-end justify-between gap-3'>
                    <span className='min-w-0'>
                      <span className='block text-sm font-medium text-foreground'>
                        {format(new Date(run.started_at), 'PPp', {
                          locale: dateLocale
                        })}
                      </span>
                      <span className='mt-1 flex items-center gap-1.5 text-xs font-normal text-muted-foreground'>
                        <Smartphone className='size-3.5' aria-hidden />
                        {run.devices_dispatched > 0
                          ? t('runDeviceSummary', {
                              succeeded: run.devices_succeeded,
                              total: run.devices_dispatched
                            })
                          : t('noDevicesDispatched')}
                      </span>
                    </span>
                    {run.devices_failed > 0 ? (
                      <span className='shrink-0 text-xs font-medium text-destructive'>
                        {t('failedDevices', { count: run.devices_failed })}
                      </span>
                    ) : null}
                  </span>
                </Button>
              </div>
            );
          })}
        </div>
      </ScrollArea>
      {runs.length > pageSize ? (
        <TablePaginationControls
          className='shrink-0 flex-row gap-2 border-t px-3 py-2 [&>div:last-child]:flex-row [&>div:last-child]:gap-2'
          pageIndex={pageIndex}
          pageCount={pageCount}
          pageSize={pageSize}
          total={runs.length}
          showRowsPerPage={false}
          onPageIndexChange={setPageIndex}
          onPageSizeChange={() => undefined}
        />
      ) : null}
    </div>
  );
}
