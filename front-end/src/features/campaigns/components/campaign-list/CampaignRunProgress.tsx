'use client';

import { useTranslations } from 'next-intl';
import { TrendingUp } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import {
  useCampaignProgress,
  useCampaignWorkflows
} from '../../hooks/use-campaigns';
import { executionsApi } from '../../services/api';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

// ── Building blocks ───────────────────────────────────────────────────────────

function StatPill({
  label,
  tone = 'neutral'
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
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium leading-4',
        toneClass
      )}
    >
      {label}
    </span>
  );
}

function CampaignProgressBar({ value }: { value: number }) {
  const safe = Math.max(0, Math.min(100, value));
  return (
    <div
      className='h-2 w-full overflow-hidden rounded-full bg-muted/80 ring-1 ring-border/50'
      role='progressbar'
      aria-valuenow={safe}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className='h-full rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-[width] duration-300 ease-out'
        style={{ width: `${safe}%` }}
      />
    </div>
  );
}

// ── Main: trigger button + popover ────────────────────────────────────────────

export function CampaignRunProgress({
  campaignId,
  isRunning
}: {
  campaignId: string;
  isRunning: boolean;
}) {
  const t = useTranslations('campaignsFeature.list');

  // Temporal workflows
  const { data: wfData } = useCampaignWorkflows(campaignId, isRunning);
  const workflows = wfData?.workflows ?? [];

  const shouldUseLegacyFallback =
    isRunning && wfData !== undefined && workflows.length === 0;
  const { data: legacyProgress } = useCampaignProgress(
    campaignId,
    shouldUseLegacyFallback
  );

  const { data: latestExecution } = useQuery({
    queryKey: ['campaign-latest-execution', campaignId],
    queryFn: () => executionsApi.list({ campaignId, limit: 1, offset: 0 }),
    enabled: isRunning && workflows.length === 0,
    refetchInterval: isRunning ? 8_000 : false,
    refetchOnWindowFocus: false
  });
  const latestExecId = latestExecution?.items?.[0]?.id;
  const { data: execSummary } = useQuery({
    queryKey: ['execution-summary', latestExecId],
    queryFn: () => executionsApi.summary(latestExecId!),
    enabled: isRunning && workflows.length === 0 && !!latestExecId,
    refetchInterval: isRunning ? 8_000 : false,
    refetchOnWindowFocus: false
  });

  if (!isRunning) return null;

  // Derive a single { pct, content } shape so the popover is uniform.
  let pct = 0;
  let content: React.ReactNode = null;

  if (workflows.length > 0) {
    const total = workflows.length;
    const completed = workflows.filter((w) => w.status === 'COMPLETED').length;
    const failed = workflows.filter(
      (w) =>
        w.status === 'FAILED' ||
        w.status === 'CANCELLED' ||
        w.status === 'TERMINATED'
    ).length;
    const running = workflows.filter((w) => w.status === 'RUNNING').length;
    const paused = workflows.filter((w) => w.status === 'PAUSED').length;
    const terminal = completed + failed;
    pct = total ? Math.round((terminal / total) * 100) : 0;

    content = (
      <div className='flex flex-col gap-3'>
        <div className='flex items-center justify-between gap-2'>
          <span className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
            {t('progressTitle')}
          </span>
          <span className='text-base font-bold tabular-nums text-foreground'>
            {pct}%
          </span>
        </div>
        <CampaignProgressBar value={pct} />
        <div className='flex flex-wrap items-center gap-1.5'>
          <StatPill label={`${completed}/${total}`} />
          {running > 0 && (
            <StatPill
              label={t('wfRunning', { count: running })}
              tone='running'
            />
          )}
          {paused > 0 && (
            <StatPill label={t('wfPaused', { count: paused })} tone='paused' />
          )}
          {failed > 0 && (
            <StatPill label={t('wfFailed', { count: failed })} tone='failed' />
          )}
        </div>
      </div>
    );
  } else if (legacyProgress && legacyProgress.total > 0) {
    pct = legacyProgress.pct;
    content = (
      <div className='flex flex-col gap-3'>
        <div className='flex items-center justify-between gap-2'>
          <span className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
            {t('progressTitle')}
          </span>
          <span className='text-base font-bold tabular-nums text-foreground'>
            {pct}%
          </span>
        </div>
        <CampaignProgressBar value={pct} />
        <div className='flex flex-wrap items-center gap-1.5'>
          <StatPill
            label={t('progressDone', {
              done: legacyProgress.done,
              total: legacyProgress.total
            })}
          />
          {legacyProgress.failed > 0 && (
            <StatPill
              label={t('progressFailed', { count: legacyProgress.failed })}
              tone='failed'
            />
          )}
        </div>
      </div>
    );
  } else if (execSummary) {
    const total =
      execSummary.total_devices ||
      execSummary.passed +
        execSummary.failed +
        execSummary.running +
        execSummary.pending +
        execSummary.error;
    const finished = execSummary.passed + execSummary.failed;
    pct = total ? Math.round((finished / total) * 100) : 0;
    content = (
      <div className='flex flex-col gap-3'>
        <div className='flex items-center justify-between gap-2'>
          <span className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
            {t('progressTitle')}
          </span>
          <span className='text-base font-bold tabular-nums text-foreground'>
            {pct}%
          </span>
        </div>
        <CampaignProgressBar value={pct} />
        <div className='flex flex-wrap items-center gap-1.5'>
          <StatPill label={t('progressDone', { done: finished, total })} />
          {execSummary.running > 0 && (
            <StatPill
              label={t('wfRunning', { count: execSummary.running })}
              tone='running'
            />
          )}
          {execSummary.failed > 0 && (
            <StatPill
              label={t('progressFailed', { count: execSummary.failed })}
              tone='failed'
            />
          )}
        </div>
      </div>
    );
  }

  // No data yet — render nothing rather than an empty popover.
  if (content === null) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type='button'
          aria-label={t('progressAria', { pct })}
          className={cn(
            'group inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-blue-500/30 bg-blue-500/10 px-2.5 text-xs font-semibold text-blue-700 shadow-sm ring-1 ring-transparent transition-all hover:bg-blue-500/15 hover:ring-blue-500/30 dark:text-blue-300'
          )}
        >
          <span className='relative inline-flex size-2 items-center justify-center'>
            <span className='absolute inline-flex size-2 animate-ping rounded-full bg-blue-500 opacity-60' />
            <span className='relative inline-flex size-2 rounded-full bg-blue-500' />
          </span>
          <TrendingUp className='size-3.5' aria-hidden='true' />
          <span className='tabular-nums'>{pct}%</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align='end' className='w-72 p-4'>
        {content}
      </PopoverContent>
    </Popover>
  );
}
