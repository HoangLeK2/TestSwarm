'use client';

import { format, formatDistanceStrict } from 'date-fns';
import type { Locale } from 'date-fns';
import {
  AlertCircle,
  CalendarClock,
  Clock3,
  History,
  RefreshCw,
  ServerCog,
  Smartphone
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import type { ScheduleRunOut } from '../services/api';
import {
  ScheduleRunStatusBadge,
  scheduleRunSourceLabel
} from './schedule-run-display';
import { ScheduleRunTechnicalDetails } from './schedule-run-technical-details';

function DetailSkeleton() {
  return (
    <div className='space-y-5 p-5' aria-busy='true'>
      <div className='flex items-center justify-between gap-3'>
        <Skeleton className='h-6 w-24' />
        <Skeleton className='h-4 w-32' />
      </div>
      <div className='grid grid-cols-2 gap-3'>
        <Skeleton className='h-24' />
        <Skeleton className='h-24' />
      </div>
      <Skeleton className='h-32' />
    </div>
  );
}

function DetailField({
  label,
  value,
  icon: Icon
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;
}) {
  return (
    <div className='rounded-lg border bg-background p-3'>
      <div className='flex items-center gap-2 text-xs text-muted-foreground'>
        <Icon className='size-3.5' aria-hidden />
        {label}
      </div>
      <div className='mt-1.5 text-sm font-medium text-foreground'>{value}</div>
    </div>
  );
}

export function ScheduleRunDetailPanel({
  run,
  isLoading,
  error,
  dateLocale,
  onRetry
}: {
  run: ScheduleRunOut | null;
  isLoading: boolean;
  error: unknown;
  dateLocale: Locale;
  onRetry: () => void;
}) {
  const t = useTranslations('schedulesFeature.list');

  if (isLoading) return <DetailSkeleton />;

  if (error) {
    return (
      <div className='p-5'>
        <Alert variant='destructive'>
          <AlertCircle aria-hidden />
          <AlertTitle>{t('detailsError')}</AlertTitle>
          <AlertDescription>
            <p>{t('detailsErrorDescription')}</p>
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

  if (!run) {
    return (
      <div className='flex min-h-64 flex-col items-center justify-center px-6 py-10 text-center'>
        <span className='mb-4 rounded-full bg-muted p-3 text-muted-foreground'>
          <History className='size-5' aria-hidden />
        </span>
        <p className='font-medium text-foreground'>{t('selectRunTitle')}</p>
        <p className='mt-1 max-w-sm text-sm text-muted-foreground'>
          {t('selectRunDescription')}
        </p>
      </div>
    );
  }

  const duration = run.finished_at
    ? formatDistanceStrict(
        new Date(run.started_at),
        new Date(run.finished_at),
        { locale: dateLocale }
      )
    : t('durationInProgress');
  const errorPresentation = (() => {
    if (run.error_code === 'DISPATCH_FAILED') {
      return {
        title: t('dispatchFailedTitle'),
        description: t('dispatchFailedDescription')
      };
    }
    if (run.error_code === 'TEMPORAL_RUN_NOW_FAILED') {
      return {
        title: t('runtimeFailedTitle'),
        description: t('runtimeFailedDescription')
      };
    }
    return {
      title: t('runErrorTitle'),
      description: t('runErrorDescription')
    };
  })();
  return (
    <ScrollArea className='min-h-0 flex-1' aria-live='polite'>
      <div className='space-y-5 p-4 md:p-5'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <p className='text-xs font-medium uppercase tracking-wide text-muted-foreground'>
              {t('selectedRunLabel')}
            </p>
            <h3 className='mt-1 text-base font-semibold text-foreground'>
              {format(new Date(run.started_at), 'PPPPp', {
                locale: dateLocale
              })}
            </h3>
          </div>
          <ScheduleRunStatusBadge status={run.status} />
        </div>

        <div className='grid gap-3 sm:grid-cols-2'>
          <DetailField
            icon={CalendarClock}
            label={t('runColStarted')}
            value={format(new Date(run.started_at), 'PPp', {
              locale: dateLocale
            })}
          />
          <DetailField icon={Clock3} label={t('duration')} value={duration} />
          <DetailField
            icon={ServerCog}
            label={t('triggerSource')}
            value={scheduleRunSourceLabel(run.trigger_source, t)}
          />
          <DetailField
            icon={Smartphone}
            label={t('runColDispatched')}
            value={t('deviceCount', { count: run.devices_dispatched })}
          />
        </div>

        <section aria-labelledby='run-result-title'>
          <h4 id='run-result-title' className='text-sm font-semibold'>
            {t('resultTitle')}
          </h4>
          <div className='mt-3 grid grid-cols-2 gap-3'>
            <div className='rounded-lg border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950'>
              <p className='text-xs font-medium text-emerald-800 dark:text-emerald-200'>
                {t('runColSucceeded')}
              </p>
              <p className='mt-1 text-2xl font-semibold tabular-nums text-emerald-950 dark:text-emerald-50'>
                {run.devices_succeeded}
              </p>
            </div>
            <div className='rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950'>
              <p className='text-xs font-medium text-red-800 dark:text-red-200'>
                {t('runColFailed')}
              </p>
              <p className='mt-1 text-2xl font-semibold tabular-nums text-red-950 dark:text-red-50'>
                {run.devices_failed}
              </p>
            </div>
          </div>
        </section>

        {run.error_message || run.error_code ? (
          <Alert variant='destructive'>
            <AlertCircle aria-hidden />
            <AlertTitle>{errorPresentation.title}</AlertTitle>
            <AlertDescription>
              <p>{errorPresentation.description}</p>
            </AlertDescription>
          </Alert>
        ) : (
          <Alert>
            <AlertCircle aria-hidden />
            <AlertTitle>{t('noRunErrorTitle')}</AlertTitle>
            <AlertDescription>{t('noRunErrorDescription')}</AlertDescription>
          </Alert>
        )}

        <ScheduleRunTechnicalDetails run={run} dateLocale={dateLocale} />
      </div>
    </ScrollArea>
  );
}
