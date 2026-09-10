'use client';

import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import {
  hasExecutionTrace,
  type ExecutionTraceSummary
} from '../lib/execution-trace';
import { isIntlMissingMessage } from './flow-editor/constants';

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

type ListTranslator = ReturnType<typeof useTranslations<'campaignsFeature.list'>>;

/**
 * Reason codes are emitted from workflow code, where a human message would be
 * frozen into Temporal history and could never be corrected for a run already
 * in flight. So the workflow ships the code and the UI owns the wording.
 * An untranslated code falls back to itself rather than printing the key path.
 */
function translateReasonCode(t: ListTranslator, code: string): string {
  const label = t(`reasonCode.${code}` as 'reasonCode.loop_history_limit');
  return isIntlMissingMessage(`reasonCode.${code}`, label) ? code : label;
}

function reasonCodeTitle(t: ListTranslator, code: string): string {
  const hint = t(`reasonCodeHint.${code}` as 'reasonCodeHint.loop_history_limit');
  return isIntlMissingMessage(`reasonCodeHint.${code}`, hint)
    ? code
    : `${code} — ${hint}`;
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
        <TraceChip
          label={t('monitorTraceReason')}
          value={translateReasonCode(t, trace.reasonCode)}
          title={reasonCodeTitle(t, trace.reasonCode)}
        />
      ) : null}
    </div>
  );
}
