'use client';

import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import {
  hasExecutionTrace,
  type ExecutionTraceSummary
} from '../lib/execution-trace';

type ExecutionTraceChipsProps = {
  trace: Partial<ExecutionTraceSummary> | null | undefined;
  className?: string;
  maxPathClassName?: string;
};

function TraceChip({
  label,
  value,
  title,
  className
}: {
  label: string;
  value: string;
  title?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex min-w-0 max-w-full items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[9px] leading-none text-muted-foreground',
        className
      )}
      title={title ?? value}
    >
      <span className='shrink-0 font-medium'>{label}</span>
      <span className='min-w-0 truncate font-mono'>{value}</span>
    </span>
  );
}

export function ExecutionTraceChips({
  trace,
  className,
  maxPathClassName
}: ExecutionTraceChipsProps) {
  const t = useTranslations('campaignsFeature.list');
  if (!hasExecutionTrace(trace)) return null;

  return (
    <div
      className={cn(
        'flex min-w-0 flex-wrap items-center gap-1 text-[9px]',
        className
      )}
    >
      {trace?.stepPath ? (
        <TraceChip
          label={t('monitorTracePath')}
          value={trace.stepPath}
          className={maxPathClassName}
        />
      ) : null}
      {trace?.stepId ? (
        <TraceChip label={t('monitorTraceStepId')} value={trace.stepId} />
      ) : null}
      {trace?.loopIter != null ? (
        <TraceChip
          label={t('monitorTraceLoop')}
          value={String(trace.loopIter + 1)}
        />
      ) : null}
      {trace?.branch ? (
        <TraceChip label={t('monitorTraceBranch')} value={trace.branch} />
      ) : null}
      {trace?.reasonCode ? (
        <TraceChip label={t('monitorTraceReason')} value={trace.reasonCode} />
      ) : null}
    </div>
  );
}
