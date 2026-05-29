'use client';

import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  Smartphone,
  XCircle
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useQuery } from '@tanstack/react-query';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { executionsApi } from '../../services/api';

type ExecutionSummary = {
  total_devices: number;
  passed: number;
  failed: number;
  running: number;
  pending: number;
  error: number;
};

function StatChip({
  count,
  tone
}: {
  count: number;
  tone: 'passed' | 'failed';
}) {
  const isPassed = tone === 'passed';
  const active = count > 0;
  return (
    <span
      className={cn(
        'inline-flex min-w-[2.25rem] items-center justify-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums leading-4 ring-1',
        isPassed
          ? active
            ? 'bg-emerald-500/12 text-emerald-700 ring-emerald-500/25 dark:text-emerald-300'
            : 'bg-muted/60 text-muted-foreground ring-border/60'
          : active
            ? 'bg-destructive/10 text-destructive ring-destructive/25'
            : 'bg-muted/60 text-muted-foreground ring-border/60'
      )}
    >
      {isPassed ? (
        <CheckCircle2 className='size-3 shrink-0' aria-hidden />
      ) : (
        <XCircle className='size-3 shrink-0' aria-hidden />
      )}
      {count}
    </span>
  );
}

function RunStatsProgressBar({
  passed,
  failed,
  total
}: {
  passed: number;
  failed: number;
  total: number;
}) {
  const safeTotal = Math.max(total, 1);
  const passedPct = Math.round((passed / safeTotal) * 100);
  const failedPct = Math.round((failed / safeTotal) * 100);
  const restPct = Math.max(0, 100 - passedPct - failedPct);

  return (
    <div
      className='flex h-2 w-full overflow-hidden rounded-full bg-muted/80 ring-1 ring-border/50'
      role='progressbar'
      aria-valuenow={passedPct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      {passedPct > 0 && (
        <div
          className='h-full bg-emerald-500 transition-[width] duration-300'
          style={{ width: `${passedPct}%` }}
        />
      )}
      {failedPct > 0 && (
        <div
          className='h-full bg-destructive transition-[width] duration-300'
          style={{ width: `${failedPct}%` }}
        />
      )}
      {restPct > 0 && (
        <div
          className='h-full bg-muted-foreground/20'
          style={{ width: `${restPct}%` }}
        />
      )}
    </div>
  );
}

function StatRow({
  icon: Icon,
  label,
  value,
  tone
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  tone: 'passed' | 'failed' | 'running' | 'pending' | 'error';
}) {
  const toneClass =
    tone === 'passed'
      ? 'text-emerald-600 dark:text-emerald-400'
      : tone === 'failed' || tone === 'error'
        ? 'text-destructive'
        : tone === 'running'
          ? 'text-blue-600 dark:text-blue-400'
          : 'text-amber-600 dark:text-amber-400';

  return (
    <div className='flex items-center justify-between gap-3 py-1'>
      <span className='flex items-center gap-2 text-xs text-muted-foreground'>
        <Icon className={cn('size-3.5 shrink-0', toneClass)} aria-hidden />
        {label}
      </span>
      <span
        className={cn(
          'min-w-[1.5rem] text-right text-xs font-semibold tabular-nums',
          value > 0 ? toneClass : 'text-muted-foreground'
        )}
      >
        {value}
      </span>
    </div>
  );
}

function RunStatsPopoverBody({
  s,
  total
}: {
  s: ExecutionSummary;
  total: number;
}) {
  const t = useTranslations('campaignsFeature.list');
  const finished = s.passed + s.failed;
  const successRate = total > 0 ? Math.round((s.passed / total) * 100) : 0;

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex items-start justify-between gap-2'>
        <div>
          <p className='text-xs font-semibold text-foreground'>
            {t('runStatsPopoverTitle')}
          </p>
          {total > 0 && (
            <p className='mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground'>
              <Smartphone className='size-3 shrink-0' aria-hidden />
              {t('runStatsDevices', { total })}
            </p>
          )}
        </div>
        {total > 0 && (
          <span className='text-sm font-bold tabular-nums text-foreground'>
            {successRate}%
          </span>
        )}
      </div>

      {total > 0 && (
        <RunStatsProgressBar passed={s.passed} failed={s.failed} total={total} />
      )}

      <div className='divide-y divide-border/60 rounded-md border border-border/60 bg-muted/20 px-2.5'>
        <StatRow
          icon={CheckCircle2}
          label={t('runStatsPassed')}
          value={s.passed}
          tone='passed'
        />
        <StatRow
          icon={XCircle}
          label={t('runStatsFailed')}
          value={s.failed}
          tone='failed'
        />
        <StatRow
          icon={Loader2}
          label={t('runStatsRunning')}
          value={s.running}
          tone='running'
        />
        <StatRow
          icon={Clock}
          label={t('runStatsPending')}
          value={s.pending}
          tone='pending'
        />
        <StatRow
          icon={AlertTriangle}
          label={t('runStatsError')}
          value={s.error}
          tone='error'
        />
      </div>

      {finished > 0 && total > 0 && (
        <p className='text-center text-[10px] text-muted-foreground'>
          {t('runStatsFinished', { finished, total })}
        </p>
      )}
    </div>
  );
}

export function CampaignRunStats({ campaignId }: { campaignId: string }) {
  const t = useTranslations('campaignsFeature.list');
  const latest = useQuery({
    queryKey: ['campaign-latest-execution', campaignId],
    queryFn: () => executionsApi.list({ campaignId, limit: 1, offset: 0 }),
    staleTime: 10_000,
    refetchInterval: 15_000
  });

  const ex = latest.data?.items?.[0];
  const summary = useQuery({
    queryKey: ['execution-summary', ex?.id],
    queryFn: () => executionsApi.summary(ex!.id),
    enabled: !!ex?.id,
    staleTime: 10_000,
    refetchInterval: 15_000
  });

  if (!ex && !latest.isLoading)
    return <span className='text-[11px] text-muted-foreground'>—</span>;
  if (!ex) return <span className='text-[11px] text-muted-foreground'>…</span>;
  if (!summary.data && summary.isLoading)
    return <span className='text-[11px] text-muted-foreground'>…</span>;
  if (!summary.data)
    return <span className='text-[11px] text-muted-foreground'>—</span>;

  const s = summary.data;
  const total =
    s.total_devices || s.passed + s.failed + s.running + s.pending + s.error;
  const inFlight = s.running + s.pending;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type='button'
          className={cn(
            'group inline-flex cursor-pointer items-center gap-1 rounded-md border border-transparent px-1 py-0.5 transition-colors',
            'hover:border-border/80 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
          )}
          aria-label={t('runStatsCompact', {
            passed: s.passed,
            failed: s.failed
          })}
        >
          <StatChip count={s.passed} tone='passed' />
          <StatChip count={s.failed} tone='failed' />
          {inFlight > 0 && (
            <span className='inline-flex size-4 items-center justify-center rounded-full bg-blue-500/15 text-blue-600 dark:text-blue-300'>
              <Loader2 className='size-2.5 animate-spin' aria-hidden />
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align='start' className='w-64 p-3'>
        <RunStatsPopoverBody s={s} total={total} />
      </PopoverContent>
    </Popover>
  );
}
