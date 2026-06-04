'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  CheckCircle2,
  XCircle,
  Pause,
  Play,
  Square,
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
import { toast } from 'sonner';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import {
  useStepAction,
  useWorkflowCancel,
  useWorkflowPause,
  useWorkflowProgress,
  useWorkflowResume
} from '../../hooks/use-campaigns';
import { useExecutionEventStream } from '../../hooks/use-execution-event-stream';
import { resolveExecutionIdForWorkflow } from '../../lib/execution-event-utils';
import type { ExecutionOut, WorkflowInfo } from '../../types';
import { useCampaignFlowI18n } from '../flow-editor/flow-i18n';
import { WorkflowStepList } from '../workflow-step-list';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useConfirm } from '@/providers/modal-provider';

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
  executions?: ExecutionOut[];
}

export function WorkflowProgressCard({
  wf,
  campaignId,
  executions = []
}: Props) {
  const t = useTranslations('campaignsFeature.list');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { canExecute } = useResourcePermissions('campaigns');
  const { getStepTypeName } = useCampaignFlowI18n();
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const isActive =
    wf.status === 'RUNNING' ||
    wf.status === 'PAUSED' ||
    wf.status === 'paused_on_error';

  const executionId = useMemo(
    () => resolveExecutionIdForWorkflow(wf.workflow_id, executions),
    [wf.workflow_id, executions]
  );

  const serial = useMemo(() => {
    const fromWorkflow = parseSerial(wf.workflow_id);
    if (!wf.workflow_id.startsWith('exec_')) return fromWorkflow;
    const ex = executions.find((e) => e.id === executionId);
    const cfg = (ex?.device_config ?? {}) as Record<string, unknown>;
    return String(cfg.device_serial ?? fromWorkflow);
  }, [wf.workflow_id, executions, executionId]);

  const scenarioId = parseScenarioId(wf.workflow_id);

  const eventStream = useExecutionEventStream(executionId, {
    enabled: isActive && !!executionId,
    workflowId: wf.workflow_id,
    deviceSerial: serial
  });

  const pollProgress = useWorkflowProgress(
    wf.workflow_id,
    isActive && !eventStream.connected
  );
  const prog = eventStream.progress ?? pollProgress.data;
  const stepAction = useStepAction(campaignId);
  const workflowPause = useWorkflowPause();
  const workflowResume = useWorkflowResume();
  const workflowCancel = useWorkflowCancel();
  const controlPending =
    workflowPause.isPending ||
    workflowResume.isPending ||
    workflowCancel.isPending;

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

  const showWorkflowPause = wf.status === 'RUNNING';
  const showWorkflowResume = wf.status === 'PAUSED';
  const showWorkflowCancel = wf.status === 'RUNNING' || wf.status === 'PAUSED';

  const handleWorkflowCancel = async () => {
    const ok = await confirm({
      title: t('monitorWfCancelTitle'),
      description: `${t('monitorWfCancelConfirm')}\n\n${t('cancelUndoWarning')}`,
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
    if (!ok) return;
    workflowCancel.mutate(wf.workflow_id, {
      onSuccess: () => toast.success(t('monitorWfCancelSuccess')),
      onError: (err) => toast.error(formatFarmApiError(err, t('cancelFailed')))
    });
  };

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
          {eventStream.connected && (
            <span
              className='shrink-0 rounded-full bg-green-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-green-600 dark:text-green-400'
              title={t('monitorEventStreamLive')}
            >
              {t('monitorEventStreamLive')}
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

      {canExecute &&
      !isPausedOnError &&
      (showWorkflowPause || showWorkflowResume || showWorkflowCancel) ? (
        <div
          className='flex items-center gap-1.5 border-t bg-muted/20 px-4 py-1.5'
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          {showWorkflowPause ? (
            <Button
              size='sm'
              variant='outline'
              className='h-6 gap-1 px-2 text-[10px]'
              disabled={controlPending}
              onClick={() =>
                workflowPause.mutate(wf.workflow_id, {
                  onSuccess: () => toast.info(t('monitorWfPauseSuccess')),
                  onError: (err) =>
                    toast.error(formatFarmApiError(err, t('runFailed')))
                })
              }
            >
              <Pause size={10} />
              {t('titlePause')}
            </Button>
          ) : null}
          {showWorkflowResume ? (
            <Button
              size='sm'
              variant='outline'
              className='h-6 gap-1 px-2 text-[10px] text-green-600 hover:text-green-600'
              disabled={controlPending}
              onClick={() =>
                workflowResume.mutate(wf.workflow_id, {
                  onSuccess: () => toast.info(t('monitorWfResumeSuccess')),
                  onError: (err) =>
                    toast.error(formatFarmApiError(err, t('runFailed')))
                })
              }
            >
              <Play size={10} />
              {t('titleResume')}
            </Button>
          ) : null}
          {showWorkflowCancel ? (
            <Button
              size='sm'
              variant='ghost'
              className='h-6 gap-1 px-2 text-[10px] text-destructive hover:text-destructive'
              disabled={controlPending}
              onClick={() => void handleWorkflowCancel()}
            >
              <Square size={10} />
              {t('titleCancel')}
            </Button>
          ) : null}
        </div>
      ) : null}

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
                sseStepLog={eventStream.stepLog}
                sseConnected={eventStream.connected}
                liveProgress={{
                  current_step: current,
                  total_steps: total,
                  current_step_type: stepType,
                  message,
                  loop_iteration: loopIter
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
