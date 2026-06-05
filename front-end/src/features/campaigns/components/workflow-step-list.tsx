'use client';

/**
 * Shared step-log display used by:
 *  - WorkflowProgressCard (campaign monitor, expanded section)
 *  - DeviceStepMonitor (device tile dialog)
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Loader2,
  XCircle
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Progress } from '@/components/ui/progress';
import { scenariosApi } from '../services/api';
import { useCampaignFlowI18n } from './flow-editor/flow-i18n';
import { useWorkflowSteps } from '../hooks/use-campaigns';
import type { StepLogEntry, WorkflowInfo } from '../types';
import type { FlowStep } from './scenario-steps/types';

// ── Parse workflow ID ─────────────────────────────────────────────────────────

export function parseWorkflowId(id: string) {
  const m = id.match(/^campaign:([^:]+):device:.+:scenario:([^:]+)$/);
  const scenarioId = m?.[2] ?? '';
  return {
    campaignId: m?.[1] ?? '',
    scenarioId: scenarioId === '__sequence__' ? '' : scenarioId
  };
}

// ── Single step row ───────────────────────────────────────────────────────────

function stepOutput(logEntry?: StepLogEntry): {
  output: string;
  exitCode?: number;
  saveAs?: string;
  truncated: boolean;
} | null {
  if (!logEntry) return null;
  const details = logEntry.details ?? {};
  const output =
    typeof logEntry.output === 'string'
      ? logEntry.output
      : typeof details.output === 'string'
        ? details.output
        : '';
  if (!output) return null;
  const exitCode =
    typeof logEntry.exit_code === 'number'
      ? logEntry.exit_code
      : typeof details.exit_code === 'number'
        ? details.exit_code
        : undefined;
  const saveAs =
    typeof logEntry.save_as === 'string'
      ? logEntry.save_as
      : typeof details.save_as === 'string'
        ? details.save_as
        : undefined;
  return {
    output,
    exitCode,
    saveAs,
    truncated: Boolean(logEntry.output_truncated ?? details.output_truncated)
  };
}

export function StepRow({
  index,
  stepDef,
  logEntry,
  isCurrentlyRunning,
  currentStepType,
  currentMessage,
  loopIter,
  isPending
}: {
  index: number;
  stepDef?: FlowStep;
  logEntry?: StepLogEntry;
  isCurrentlyRunning: boolean;
  currentStepType: string;
  currentMessage: string;
  loopIter: number | null;
  isPending: boolean;
}) {
  const t = useTranslations('campaignsFeature.list');
  const { getStepTypeName, getStepDisplay: getStepDisplayI18n } =
    useCampaignFlowI18n();
  const type =
    stepDef?.type ??
    logEntry?.step_type ??
    logEntry?.type ??
    (isCurrentlyRunning ? currentStepType : '');
  const userTitle = (stepDef as Record<string, unknown> | undefined)?.[
    'title'
  ] as string | undefined;
  const { target } = stepDef ? getStepDisplayI18n(stepDef) : { target: '' };
  const label =
    userTitle?.trim() ||
    (type ? getStepTypeName(type) : t('monitorStepFallback', { n: index + 1 }));
  const sublabel = !userTitle?.trim() && target ? target : undefined;
  const depth = logEntry?.depth ?? 0;

  const isDone = !!logEntry && !isCurrentlyRunning;
  const isFailed = isDone && !logEntry.ok;
  const isOk = isDone && logEntry.ok;
  const msg = isCurrentlyRunning ? currentMessage : (logEntry?.message ?? '');
  const adbOutput = stepOutput(logEntry);

  return (
    <div
      className={cn(
        'flex items-start gap-2 border-b py-2 pr-3 text-[11px] transition-colors last:border-b-0',
        isCurrentlyRunning && 'bg-primary/5',
        isFailed && 'bg-destructive/5',
        isPending && 'opacity-40'
      )}
      style={{ paddingLeft: `${12 + depth * 14}px` }}
    >
      {/* Icon */}
      <div className='mt-0.5 w-3 shrink-0'>
        {isFailed ? (
          <XCircle size={12} className='text-destructive' />
        ) : isCurrentlyRunning ? (
          <Loader2 size={12} className='animate-spin text-primary' />
        ) : isOk ? (
          <CheckCircle2 size={12} className='text-green-500' />
        ) : (
          <Circle size={12} className='text-muted-foreground/25' />
        )}
      </div>

      {/* Number */}
      <span
        className={cn(
          'mt-0.5 w-5 shrink-0 text-[10px] tabular-nums',
          isCurrentlyRunning
            ? 'font-bold text-primary'
            : 'text-muted-foreground'
        )}
      >
        {index + 1}
      </span>

      {/* Name + sublabel + message */}
      <div className='min-w-0 flex-1'>
        <div
          className={cn(
            'truncate leading-tight',
            isCurrentlyRunning
              ? 'font-semibold text-primary'
              : isFailed
                ? 'text-destructive'
                : isOk
                  ? 'text-foreground'
                  : 'text-muted-foreground/60'
          )}
        >
          {label}
        </div>
        {sublabel && !isCurrentlyRunning && (
          <div
            className='truncate text-[10px] text-muted-foreground'
            title={sublabel}
          >
            {sublabel}
          </div>
        )}
        {isCurrentlyRunning && msg && (
          <div
            className='truncate text-[10px] italic text-primary/70'
            title={msg}
          >
            {msg}
          </div>
        )}
        {isCurrentlyRunning && loopIter !== null && (
          <div className='text-[10px] text-primary/60'>
            {t('monitorStepRowLoopRound', { n: loopIter + 1 })}
          </div>
        )}
        {isFailed && msg && (
          <div className='truncate text-[10px] text-destructive/80' title={msg}>
            {msg}
          </div>
        )}
        {adbOutput && (
          <div className='mt-1.5 rounded-md border border-border/60 bg-muted/35'>
            <div className='flex min-w-0 items-center gap-2 border-b border-border/50 px-2 py-1 text-[9px] font-medium uppercase tracking-wide text-muted-foreground'>
              <span>{t('monitorStepAdbOutput')}</span>
              {adbOutput.exitCode != null && (
                <span className='rounded bg-background px-1 py-px normal-case tracking-normal'>
                  exit {adbOutput.exitCode}
                </span>
              )}
              {adbOutput.saveAs && (
                <span
                  className='truncate rounded bg-background px-1 py-px font-mono normal-case tracking-normal'
                  title={`\${${adbOutput.saveAs}}`}
                >
                  {`\${${adbOutput.saveAs}}`}
                </span>
              )}
              {adbOutput.truncated && (
                <span className='rounded bg-amber-500/10 px-1 py-px text-amber-700 dark:text-amber-300'>
                  {t('monitorStepOutputTruncated')}
                </span>
              )}
            </div>
            <pre className='max-h-28 overflow-auto whitespace-pre-wrap break-words px-2 py-1.5 font-mono text-[10px] leading-relaxed text-foreground'>
              {adbOutput.output}
            </pre>
          </div>
        )}
      </div>

      {/* Type badge */}
      {type && (
        <span
          className={cn(
            'mt-0.5 shrink-0 rounded px-1 py-px text-[9px] font-bold uppercase tracking-wide',
            isCurrentlyRunning
              ? 'bg-primary/15 text-primary'
              : isOk
                ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                : isFailed
                  ? 'bg-destructive/10 text-destructive'
                  : 'bg-muted text-muted-foreground/50'
          )}
        >
          {getStepTypeName(type)}
        </span>
      )}
    </div>
  );
}

// ── Full step list for one workflow ───────────────────────────────────────────

interface WorkflowStepListProps {
  wf: WorkflowInfo;
  /** Maximum height of the scrollable step list (default: 360px) */
  maxHeight?: string;
  sseStepLog?: StepLogEntry[];
  sseConnected?: boolean;
  /** When SSE is active, progress fields from the event stream (skips poll). */
  liveProgress?: {
    current_step: number;
    total_steps: number;
    current_step_type: string;
    message: string;
    loop_iteration: number | null;
  };
}

export function WorkflowStepList({
  wf,
  maxHeight = '360px',
  sseStepLog,
  sseConnected = false,
  liveProgress
}: WorkflowStepListProps) {
  const t = useTranslations('campaignsFeature.list');
  const isActive = wf.status === 'RUNNING' || wf.status === 'PAUSED';
  const { campaignId, scenarioId } = parseWorkflowId(wf.workflow_id);

  const useSseSteps = sseConnected && (sseStepLog?.length ?? 0) > 0;

  const { data: stepLog, isLoading: logLoading } = useWorkflowSteps(
    wf.workflow_id,
    isActive && !useSseSteps
  );

  const { data: scenario, isLoading: scenarioLoading } = useQuery({
    queryKey: ['scenario-steps', campaignId, scenarioId],
    queryFn: () => scenariosApi.get(campaignId, scenarioId),
    enabled: !!campaignId && !!scenarioId,
    staleTime: 30_000
  });

  if (scenarioLoading || (!useSseSteps && logLoading)) {
    return (
      <div className='flex items-center gap-2 py-4 text-xs text-muted-foreground'>
        <Loader2 size={12} className='animate-spin' />{' '}
        {t('monitorStepListLoading')}
      </div>
    );
  }

  const scenarioDefs: FlowStep[] = (scenario?.steps ?? []) as FlowStep[];
  const executedSteps: StepLogEntry[] = useSseSteps
    ? (sseStepLog ?? [])
    : (stepLog?.steps ?? []);

  const current = liveProgress?.current_step ?? 0;
  const total =
    liveProgress?.total_steps ?? scenarioDefs.length ?? executedSteps.length;
  const stepType = liveProgress?.current_step_type ?? '';
  const message = liveProgress?.message ?? '';
  const loopIter =
    liveProgress?.loop_iteration != null && liveProgress.loop_iteration >= 0
      ? liveProgress.loop_iteration
      : null;
  const pct =
    total > 0
      ? Math.round(((isActive ? current : executedSteps.length) / total) * 100)
      : wf.status === 'COMPLETED'
        ? 100
        : 0;

  const logByIndex = new Map(executedSteps.map((e) => [e.index, e]));
  const rowCount = Math.max(
    total,
    scenarioDefs.length,
    executedSteps.length > 0
      ? (executedSteps[executedSteps.length - 1]?.index ?? 0) + 1
      : 0
  );

  return (
    <div className='space-y-2'>
      {/* Progress bar */}
      <div className='flex items-center gap-2'>
        <Progress
          value={pct}
          className={cn(
            'h-1.5 flex-1',
            wf.status === 'FAILED' && '[&>div]:bg-destructive',
            wf.status === 'PAUSED' && '[&>div]:bg-amber-500',
            wf.status === 'COMPLETED' && '[&>div]:bg-green-500'
          )}
        />
        <span className='shrink-0 text-[10px] tabular-nums text-muted-foreground'>
          {isActive
            ? `${current}/${total}`
            : `${executedSteps.length}/${total}`}
        </span>
      </div>

      {/* Step list */}
      {rowCount > 0 ? (
        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='overflow-y-auto' style={{ maxHeight }}>
            {Array.from({ length: rowCount }).map((_, i) => {
              const logEntry = logByIndex.get(i);
              const stepDef = scenarioDefs[i];
              const isCurrentlyRunning = isActive && i === current && !logEntry;

              return (
                <StepRow
                  key={i}
                  index={i}
                  stepDef={stepDef}
                  logEntry={logEntry}
                  isCurrentlyRunning={isCurrentlyRunning}
                  currentStepType={stepType}
                  currentMessage={message}
                  loopIter={loopIter}
                  isPending={!logEntry && !isCurrentlyRunning && i > current}
                />
              );
            })}
          </div>
        </div>
      ) : (
        <p className='py-4 text-center text-[11px] text-muted-foreground'>
          {t('monitorStepListEmpty')}
        </p>
      )}

      {/* Summary */}
      {wf.status === 'COMPLETED' && (
        <div className='flex items-center gap-1.5 text-[11px] text-green-600 dark:text-green-400'>
          <CheckCircle2 size={12} />{' '}
          {t('monitorStepListCompletedSummary', {
            count: executedSteps.length
          })}
        </div>
      )}
      {wf.status === 'FAILED' && (
        <div className='flex items-center gap-1.5 text-[11px] text-destructive'>
          <AlertCircle size={12} />
          {message || t('monitorStepListFailedAt', { step: current + 1 })}
        </div>
      )}
    </div>
  );
}
