'use client';

import {
  Activity,
  ChevronDown,
  Loader2,
  Pause,
  Play,
  Square
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import {
  useContinuousCrawlControl,
  useContinuousCrawlProgress
} from '../../hooks/use-campaigns';
import {
  boundedCrawlRows,
  crawlCompletion,
  type ContinuousCrawlControl,
  type ContinuousCrawlHealth
} from '../../lib/continuous-crawl-monitor';

const healthClass: Record<ContinuousCrawlHealth, string> = {
  healthy: 'bg-emerald-500',
  degraded: 'bg-amber-500',
  critical: 'bg-destructive'
};

export function ContinuousCrawlDashboard({
  campaignId,
  enabled
}: {
  campaignId: string;
  enabled: boolean;
}) {
  const t = useTranslations('campaignsFeature.list');
  const {
    data: progress,
    isLoading,
    error
  } = useContinuousCrawlProgress(campaignId, enabled);
  const { mutateAsync: control, isPending } = useContinuousCrawlControl();

  if (!enabled) return null;
  if (isLoading) {
    return (
      <div className='flex items-center gap-2 border-b bg-muted/10 px-4 py-4 text-sm text-muted-foreground sm:px-6'>
        <Loader2 className='size-4 animate-spin' />
        {t('crawlLoading')}
      </div>
    );
  }
  if (error || !progress) {
    return (
      <p className='border-b bg-muted/10 px-4 py-4 text-sm text-muted-foreground sm:px-6'>
        {t('crawlUnavailable')}
      </p>
    );
  }

  const completion = crawlCompletion(progress);
  const rows = boundedCrawlRows(progress);
  const completed = progress.succeeded + progress.failed;
  const act = async (action: ContinuousCrawlControl) => {
    try {
      await control({ campaignId, control: action });
    } catch (err) {
      toast.error(formatFarmApiError(err, t('crawlControlFailed')));
    }
  };

  return (
    <section className='border-b bg-muted/10 tabular-nums'>
      <div className='flex flex-wrap items-start gap-3 px-4 py-5 sm:px-6'>
        <div className='flex size-9 items-center justify-center rounded-full bg-primary/10 text-primary'>
          <Activity className='size-4' />
        </div>
        <div className='min-w-0 flex-1'>
          <p className='text-xs font-medium text-muted-foreground'>
            {t('crawlAutomation')}
          </p>
          <h2 className='text-base font-semibold'>{t('crawlCurrentRun')}</h2>
          <div className='mt-1 flex items-center gap-2 text-sm'>
            <span
              className={`size-2 rounded-full ${healthClass[progress.health]}`}
            />
            <span>{t(`crawlStatuses.${progress.status}`)}</span>
          </div>
        </div>
        <div className='flex flex-wrap justify-end gap-2'>
          {progress.status === 'running' ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button size='sm' variant='outline' disabled={isPending}>
                  <Pause className='mr-1.5 size-3.5' />
                  {t('titlePause')}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t('crawlPauseTitle')}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t('crawlPauseDescription')}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t('back')}</AlertDialogCancel>
                  <AlertDialogAction onClick={() => void act('pause')}>
                    {t('titlePause')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : progress.status === 'paused' || progress.status === 'pausing' ? (
            <Button
              size='sm'
              variant='outline'
              disabled={isPending}
              onClick={() => void act('resume')}
            >
              <Play className='mr-1.5 size-3.5' />
              {t('titleResume')}
            </Button>
          ) : null}
          {['running', 'pausing', 'paused', 'cancelling'].includes(
            progress.status
          ) ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  size='sm'
                  variant='ghost'
                  className='text-destructive'
                  disabled={isPending || progress.status === 'cancelling'}
                >
                  <Square className='mr-1.5 size-3.5' />
                  {t('crawlStopRun')}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t('crawlStopTitle')}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t('crawlStopDescription')}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t('back')}</AlertDialogCancel>
                  <AlertDialogAction
                    className='bg-destructive text-destructive-foreground hover:bg-destructive/90'
                    onClick={() => void act('cancel')}
                  >
                    {t('crawlStopRun')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : null}
        </div>
      </div>

      <div className='grid grid-cols-3 border-y bg-card/70'>
        {[
          [t('crawlCompleted'), completed],
          [t('crawlActive'), progress.active],
          [t('crawlNeedsAttention'), progress.failed]
        ].map(([label, value]) => (
          <div
            key={String(label)}
            className='min-w-0 border-r px-4 py-4 last:border-r-0 sm:px-6'
          >
            <div className='text-xl font-semibold sm:text-2xl'>{value}</div>
            <div className='truncate text-xs text-muted-foreground'>
              {label}
            </div>
          </div>
        ))}
      </div>

      {completion.percent != null ? (
        <div className='h-1 bg-muted'>
          <div
            className='h-full bg-primary transition-[width]'
            style={{ width: `${completion.percent}%` }}
          />
        </div>
      ) : null}

      <div className='px-4 py-4 sm:px-6'>
        <p className='text-sm font-medium'>
          {t(`crawlHealthMessage.${progress.health}`)}
        </p>
        {progress.status === 'pausing' ? (
          <p className='mt-1 text-xs text-muted-foreground'>
            {t('crawlPausingDetail', { count: progress.active })}
          </p>
        ) : null}
      </div>

      <Collapsible className='border-t'>
        <CollapsibleTrigger className='group flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-muted/40 sm:px-6'>
          {t('crawlOperationalDetails')}
          <ChevronDown className='size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180' />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className='grid border-t md:grid-cols-2 md:divide-x'>
            <div className='min-w-0 px-4 py-4 sm:px-6'>
              <h3 className='mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
                {t('crawlDevices')}
              </h3>
              <div className='grid gap-2 sm:grid-cols-2'>
                {rows.lanes.map((lane) => (
                  <div
                    key={lane.device_serial}
                    className='flex min-w-0 items-center gap-2 rounded-md border bg-card px-3 py-2 text-xs'
                  >
                    <span
                      className={`size-2 shrink-0 rounded-full ${lane.status === 'failed' || lane.status === 'offline' ? 'bg-destructive' : lane.status === 'running' ? 'bg-emerald-500' : 'bg-muted-foreground'}`}
                    />
                    <span className='min-w-0 flex-1 truncate font-medium'>
                      {lane.device_serial}
                    </span>
                    <span className='shrink-0 text-muted-foreground'>
                      {lane.completed}/{lane.failed}
                    </span>
                  </div>
                ))}
                {rows.lanes.length === 0 ? (
                  <p className='text-xs text-muted-foreground'>
                    {t('crawlNoLanes')}
                  </p>
                ) : null}
              </div>
            </div>
            <div className='min-w-0 border-t px-4 py-4 sm:px-6 md:border-t-0'>
              <h3 className='mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
                {t('crawlRecentItems')}
              </h3>
              <div className='space-y-2'>
                {rows.targets.map((target) => (
                  <div
                    key={target.target_id}
                    className='flex min-w-0 gap-3 text-xs'
                  >
                    <span className='min-w-0 flex-1 truncate'>
                      {target.label || target.target_id}
                    </span>
                    <span className='shrink-0 text-muted-foreground'>
                      {t(`crawlTargetStatuses.${target.status}`)}
                    </span>
                  </div>
                ))}
                {rows.targets.length === 0 ? (
                  <p className='text-xs text-muted-foreground'>
                    {t('crawlNoRecentTargets')}
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
