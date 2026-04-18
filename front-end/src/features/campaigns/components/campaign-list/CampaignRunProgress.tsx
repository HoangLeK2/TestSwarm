'use client';

import { useTranslations } from 'next-intl';
import {
  useCampaignProgress,
  useCampaignWorkflows,
} from '../../hooks/use-campaigns';

function StatPill({
  label,
  tone = 'neutral',
}: {
  label: string;
  tone?: 'neutral' | 'running' | 'paused' | 'failed';
}) {
  const toneClass =
    tone === 'running'
      ? 'bg-blue-500/10 text-blue-700 dark:text-blue-300'
      : tone === 'paused'
        ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
        : tone === 'failed'
          ? 'bg-destructive/10 text-destructive'
          : 'bg-muted text-foreground';
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium leading-4 ${toneClass}`}
    >
      {label}
    </span>
  );
}

function CampaignProgressBar({ value }: { value: number }) {
  const safe = Math.max(0, Math.min(100, value));
  return (
    <div className='h-2 w-full overflow-hidden rounded-full bg-muted/80 ring-1 ring-border/50'>
      <div
        className='h-full rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-[width] duration-300 ease-out'
        style={{ width: `${safe}%` }}
      />
    </div>
  );
}

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

 
  const shouldUseLegacyFallback = isRunning && wfData !== undefined && workflows.length === 0;
  const { data: legacyProgress } = useCampaignProgress(campaignId, shouldUseLegacyFallback);

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
      <div className='mt-2 flex min-w-0 flex-col gap-1.5 border-t border-border/40 pt-2'>
        <div className='flex items-center justify-between gap-2'>
          <div className='flex min-w-0 flex-wrap items-center gap-1.5'>
            <StatPill label={`${completed}/${total}`} />
            {running > 0 && <StatPill label={t('wfRunning', { count: running })} tone='running' />}
            {paused > 0 && <StatPill label={t('wfPaused', { count: paused })} tone='paused' />}
            {failed > 0 && <StatPill label={t('wfFailed', { count: failed })} tone='failed' />}
          </div>
          <span className='shrink-0 tabular-nums text-xs font-semibold text-foreground'>{pct}%</span>
        </div>
        <CampaignProgressBar value={pct} />
      </div>
    );
  }

  // Legacy fallback
  if (!legacyProgress || legacyProgress.total === 0) return null;

  return (
    <div className='mt-2 flex min-w-0 flex-col gap-1.5 border-t border-border/40 pt-2'>
      <div className='flex items-center justify-between gap-2'>
        <div className='flex min-w-0 flex-wrap items-center gap-1.5'>
          <StatPill
            label={t('progressDone', { done: legacyProgress.done, total: legacyProgress.total })}
          />
          {legacyProgress.failed > 0 && <StatPill label={t('progressFailed', { count: legacyProgress.failed })} tone='failed' />}
        </div>
        <span className='shrink-0 tabular-nums text-xs font-semibold text-foreground'>
          {legacyProgress.pct}%
        </span>
      </div>
      <CampaignProgressBar value={legacyProgress.pct} />
    </div>
  );
}
