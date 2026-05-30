'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  CheckCircle2,
  XCircle,
  Pause,
  Loader2,
  Clock,
  ChevronDown,
  ChevronRight,
  Smartphone,
  List,
  AlertTriangle,
  RefreshCw,
  SkipForward
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Progress } from '@/components/ui/progress';
import { Button } from '@/components/ui/button';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import { useWorkflowProgress, useStepAction } from '../../hooks/use-campaigns';
import type { WorkflowInfo } from '../../types';
import { useCampaignFlowI18n } from '../flow-editor/flow-i18n';
import { WorkflowStepList } from '../workflow-step-list';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

// ── Helpers ──────────────────────────────────────────────────────────────────

function parseSerial(workflowId: string): string {
  const m = workflowId.match(/^campaign:[^:]+:device:(.+):scenario:[^:]+$/);
  return m ? m[1] : workflowId;
}

function parseScenarioId(workflowId: string): string {
  const m = workflowId.match(/:scenario:([^:]+)$/);
  if (!m || m[1] === '__sequence__') return '';
  return m[1];
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const t = useTranslations('campaignsFeature.list');
  const cfg: Record<
    string,
    { icon: React.ReactNode; cls: string; label: string }
  > = {
    RUNNING: {
      icon: <Loader2 size={10} className='animate-spin' />,
      cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
      label: t('monitorWfStatusRunning')
    },
    COMPLETED: {
      icon: <CheckCircle2 size={10} />,
      cls: 'bg-green-500/15 text-green-600 dark:text-green-400',
      label: t('monitorWfStatusCompleted')
    },
    FAILED: {
      icon: <XCircle size={10} />,
      cls: 'bg-red-500/15 text-red-600 dark:text-red-400',
      label: t('monitorWfStatusFailed')
    },
    PAUSED: {
      icon: <Pause size={10} />,
      cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
      label: t('monitorWfStatusPaused')
    },
    paused_on_error: {
      icon: <AlertTriangle size={10} />,
      cls: 'bg-orange-500/15 text-orange-600 dark:text-orange-400 animate-pulse',
      label: t('monitorWfStatusPausedOnError')
    },
    CANCELLED: {
      icon: <XCircle size={10} />,
      cls: 'bg-muted text-muted-foreground',
      label: t('monitorWfStatusCancelled')
    },
    TERMINATED: {
      icon: <XCircle size={10} />,
      cls: 'bg-muted text-muted-foreground',
      label: t('monitorWfStatusTerminated')
    }
  };
  const c = cfg[status] ?? {
    icon: <Clock size={10} />,
    cls: 'bg-muted text-muted-foreground',
    label: status
  };
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-bold',
        c.cls
      )}
    >
      {c.icon}
      {c.label}
    </span>
  );
}

// ── Step dots ─────────────────────────────────────────────────────────────────

function StepDots({ current, total }: { current: number; total: number }) {
  if (total === 0) return null;
  const MAX = 20;
  const dots = total <= MAX ? total : MAX;
  const ratio = total <= MAX ? 1 : total / MAX;
  return (
    <div className='flex items-center gap-[2px]'>
      {Array.from({ length: dots }).map((_, i) => {
        const stepIdx = Math.round(i * ratio);
        const done = stepIdx < current;
        const active = stepIdx === current;
        return (
          <div
            key={i}
            className={cn(
              'h-1.5 rounded-full transition-all',
              active
                ? 'w-3 bg-primary'
                : done
                  ? 'w-1.5 bg-primary/60'
                  : 'w-1.5 bg-muted'
            )}
          />
        );
      })}
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

interface Props {
  wf: WorkflowInfo;
  campaignId: string;
}

export function WorkflowProgressCard({ wf, campaignId }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { canExecute } = useResourcePermissions('campaigns');
  const { getStepTypeName } = useCampaignFlowI18n();
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const isActive =
    wf.status === 'RUNNING' ||
    wf.status === 'PAUSED' ||
    wf.status === 'paused_on_error';
  const { data: prog } = useWorkflowProgress(wf.workflow_id, isActive);
  const stepAction = useStepAction(campaignId);

  const serial = parseSerial(wf.workflow_id);
  const scenarioId = parseScenarioId(wf.workflow_id);

  const current = prog?.current_step ?? 0;
  const total = prog?.total_steps ?? 0;
  const pct =
    total > 0
      ? Math.round((current / total) * 100)
      : wf.status === 'COMPLETED'
        ? 100
        : 0;
  const stepType = prog?.current_step_type ?? '';
  const message = prog?.message ?? '';
  const loopIter =
    prog?.loop_iteration != null && prog.loop_iteration >= 0
      ? prog.loop_iteration
      : null;
  // paused_on_error can come from the live progress poll (more up-to-date than wf.status)
  // dismissed is optimistically set when user clicks Retry/Skip to hide the bar immediately.
  const isPausedOnError =
    !dismissed &&
    (prog?.status === 'paused_on_error' || wf.status === 'paused_on_error');
  const errorMessage =
    prog?.error_message || (isPausedOnError ? message : null);

  // When the status transitions back to running (after retry/skip was acknowledged by
  // the server) reset dismissed so the bar can reappear if the workflow errors again.
  useEffect(() => {
    if (prog?.status === 'running' || prog?.status === 'RUNNING') {
      setDismissed(false);
    }
  }, [prog?.status]);

  return (
    <div className={cn('transition-colors', expanded && 'bg-accent/20')}>
      {/* ── Summary row (always visible, clickable) ── */}
      <button
        type='button'
        className='w-full px-4 py-3 text-left transition-colors hover:bg-accent/40'
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Row 1: chevron + serial + status */}
        <div className='mb-2 flex items-center gap-2'>
          {expanded ? (
            <ChevronDown size={12} className='shrink-0 text-muted-foreground' />
          ) : (
            <ChevronRight
              size={12}
              className='shrink-0 text-muted-foreground'
            />
          )}
          <Smartphone size={11} className='shrink-0 text-muted-foreground' />
          <span
            className='flex-1 truncate font-mono text-[11px] font-semibold'
            title={serial}
          >
            {serial}
          </span>
          {scenarioId && (
            <span
              className='shrink-0 font-mono text-[9px] text-muted-foreground'
              title={scenarioId}
            >
              #{scenarioId.slice(0, 8)}
            </span>
          )}
          <StatusBadge status={wf.status} />
        </div>

        {/* Row 2: progress bar + counter */}
        <div className='mb-1.5 flex items-center gap-2 pl-[26px]'>
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
            {total > 0 ? `${current}/${total}` : pct > 0 ? `${pct}%` : '—'}
          </span>
        </div>

        {/* Row 3: step dots */}
        {total > 0 && (
          <div className='mb-1.5 pl-[26px]'>
            <StepDots current={current} total={total} />
          </div>
        )}

        {/* Row 4: current step type + message */}
        {isActive && (
          <div className='flex items-center gap-1.5 pl-[26px] text-[10px] text-muted-foreground'>
            {stepType && (
              <span className='rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-bold text-primary'>
                {getStepTypeName(stepType)}
              </span>
            )}
            {loopIter !== null && (
              <span className='text-[9px]'>
                {t('monitorWfLoopRound', { n: loopIter + 1 })}
              </span>
            )}
            {message && (
              <span className='flex-1 truncate italic' title={message}>
                {message}
              </span>
            )}
          </div>
        )}

        {wf.status === 'FAILED' && message && (
          <p
            className='mt-1 truncate pl-[26px] text-[10px] text-destructive'
            title={message}
          >
            {message}
          </p>
        )}

        {isPausedOnError && errorMessage && (
          <p
            className='mt-1 truncate pl-[26px] text-[10px] text-orange-600 dark:text-orange-400'
            title={errorMessage}
          >
            {t('monitorWfErrorPrefix')} {errorMessage}
          </p>
        )}
      </button>

      {/* ── Retry / Skip bar (shown when paused on error) ── */}
      {isPausedOnError && canExecute && (
        <div className='flex items-center gap-2 border-t bg-orange-500/5 px-4 py-2'>
          <AlertTriangle size={11} className='shrink-0 text-orange-500' />
          <span className='flex-1 text-[10px] text-orange-600 dark:text-orange-400'>
            {t('monitorWfPausedPrompt')}
          </span>
          <Button
            size='sm'
            variant='outline'
            className='h-6 gap-1 border-orange-400 px-2 text-[10px] text-orange-600 hover:bg-orange-500/10'
            disabled={stepAction.isPending}
            onClick={(e) => {
              e.stopPropagation();
              setDismissed(true);
              stepAction.mutate(
                { action: 'retry', deviceSerial: serial },
                {
                  onError: () => setDismissed(false)
                }
              );
            }}
          >
            <RefreshCw
              size={10}
              className={stepAction.isPending ? 'animate-spin' : ''}
            />
            {t('monitorActionRetry')}
          </Button>
          <Button
            size='sm'
            variant='outline'
            className='h-6 gap-1 px-2 text-[10px]'
            disabled={stepAction.isPending}
            onClick={(e) => {
              e.stopPropagation();
              setDismissed(true);
              stepAction.mutate(
                { action: 'skip', deviceSerial: serial },
                {
                  onError: () => setDismissed(false)
                }
              );
            }}
          >
            <SkipForward size={10} />
            {t('monitorActionDismiss')}
          </Button>
        </div>
      )}

      {/* ── Expanded: device left + steps right ── */}
      {expanded && (
        <div className='overflow-hidden border-t bg-card'>
          <div className='flex min-h-0 divide-x overflow-x-auto'>
            <div className='w-[320px] shrink-0 p-2 md:w-[420px]'>
              <DeviceControlEmbed
                initialSerial={serial}
                compact
                hideStepMonitor
                readOnlyPreview
              />
            </div>
            <div className='min-w-0 flex-1 px-3 py-3'>
              <p className='mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                <List size={10} /> {t('monitorStepsHeading')}
              </p>
              <WorkflowStepList
                wf={wf}
                maxHeight='min(560px, calc(90dvh - 320px))'
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
