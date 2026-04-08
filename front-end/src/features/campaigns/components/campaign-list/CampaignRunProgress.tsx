'use client';

import { useTranslations } from 'next-intl';
import { Progress } from '@/components/ui/progress';
import {
  useCampaignProgress,
  useCampaignWorkflows,
} from '../../hooks/use-campaigns';

export function CampaignRunProgress({
  campaignId,
  isRunning,
}: {
  campaignId: string;
  isRunning: boolean;
}) {
  const t = useTranslations('campaignsFeature.list');

  // Temporal workflows
  const { data: wfData } = useCampaignWorkflows(campaignId, isRunning);
  const workflows = wfData?.workflows ?? [];

  // Legacy task progress (fallback)
  const { data: legacyProgress } = useCampaignProgress(campaignId, isRunning && workflows.length === 0);

  if (!isRunning) return null;

  // Temporal mode
  if (workflows.length > 0) {
    const total = workflows.length;
    const completed = workflows.filter((w) => w.status === 'COMPLETED').length;
    const failed = workflows.filter((w) => w.status === 'FAILED' || w.status === 'CANCELLED' || w.status === 'TERMINATED').length;
    const running = workflows.filter((w) => w.status === 'RUNNING').length;
    const paused = workflows.filter((w) => w.status === 'PAUSED').length;
    const terminal = completed + failed;
    const pct = total ? Math.round((terminal / total) * 100) : 0;

    return (
      <div className='mt-2 flex min-w-0 flex-col gap-1 border-t border-border/30 pt-2 text-[11px]'>
        <div className='flex items-start justify-between gap-2'>
          <div className='flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5'>
            <span className='font-medium tabular-nums text-foreground'>{completed}/{total}</span>
            {running > 0 && (
              <span className='text-blue-600 dark:text-blue-400'>{t('wfRunning', { count: running })}</span>
            )}
            {paused > 0 && (
              <span className='text-amber-600 dark:text-amber-400'>{t('wfPaused', { count: paused })}</span>
            )}
            {failed > 0 && <span className='font-medium text-destructive'>{t('wfFailed', { count: failed })}</span>}
          </div>
          <span className='shrink-0 tabular-nums text-sm font-semibold leading-none text-foreground'>{pct}%</span>
        </div>
        <Progress value={pct} className='h-1.5 w-full bg-muted' />
      </div>
    );
  }

  // Legacy fallback
  if (!legacyProgress || legacyProgress.total === 0) return null;

  return (
    <div className='mt-2 flex min-w-0 flex-col gap-1 border-t border-border/30 pt-2 text-[11px]'>
      <div className='flex items-start justify-between gap-2'>
        <div className='flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5'>
          <span className='font-medium text-foreground'>
            {t('progressDone', { done: legacyProgress.done, total: legacyProgress.total })}
          </span>
          {legacyProgress.failed > 0 && (
            <span className='font-medium text-destructive'>
              {t('progressFailed', { count: legacyProgress.failed })}
            </span>
          )}
        </div>
        <span className='shrink-0 tabular-nums text-sm font-semibold leading-none text-foreground'>
          {legacyProgress.pct}%
        </span>
      </div>
      <Progress value={legacyProgress.pct} className='h-1.5 w-full bg-muted' />
    </div>
  );
}
