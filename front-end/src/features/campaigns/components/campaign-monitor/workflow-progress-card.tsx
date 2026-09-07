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
  SkipForward,
  MonitorPlay,
  MonitorOff,
  Activity
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
import {
  claimCampaignMonitorLiveMirror,
  getCampaignMonitorLiveMirrorSerial,
  releaseCampaignMonitorLiveMirror,
  subscribeCampaignMonitorLiveMirror
} from '../../lib/campaign-monitor-live-mirror';
import { resolveExecutionIdForWorkflow } from '../../lib/execution-event-utils';
import { executionTraceFromRecord } from '../../lib/execution-trace';
import { detectActiveRecoveryFromEvents } from '../../lib/workflow-incident-display';
import { humanizeSessionGateMessage } from '../../lib/session-gate-message';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { WorkflowScenarioModeBadge } from '../workflow-scenario-mode-badge';
import type { ExecutionOut, WorkflowInfo, WorkflowProgress } from '../../types';
import { useCampaignFlowI18n } from '../flow-editor/flow-i18n';
import { WorkflowStepList } from '../workflow-step-list';
import { ExecutionTraceChips } from '../execution-trace-chips';
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

function compactActivityId(activityId: string | null | undefined): string {
  if (!activityId) return '';
  if (activityId.length <= 30) return activityId;
  return `${activityId.slice(0, 18)}...${activityId.slice(-10)}`;
}

function mergeProgressSources(
  eventProgress: Partial<WorkflowProgress> | null,
  polledProgress: WorkflowProgress | undefined
): Partial<WorkflowProgress> | undefined {
  if (!eventProgress) return polledProgress;
  return {
    ...polledProgress,
    ...eventProgress,
    current_activity_id:
      polledProgress?.current_activity_id ?? eventProgress.current_activity_id,
    current_step_activity_id:
      polledProgress?.current_step_activity_id ??
      eventProgress.current_step_activity_id,
    current_phase: polledProgress?.current_phase ?? eventProgress.current_phase,
    side_effect_class:
      polledProgress?.side_effect_class ?? eventProgress.side_effect_class,
    activity_attempt:
      polledProgress?.activity_attempt ?? eventProgress.activity_attempt,
    activity_state:
      polledProgress?.activity_state ?? eventProgress.activity_state,
    stalled_reason:
      polledProgress?.stalled_reason ?? eventProgress.stalled_reason,
    stalled_after_ms:
      polledProgress?.stalled_after_ms ?? eventProgress.stalled_after_ms,
    stalled_threshold_ms:
      polledProgress?.stalled_threshold_ms ??
      eventProgress.stalled_threshold_ms,
    activity_retrying:
      polledProgress?.activity_retrying ?? eventProgress.activity_retrying
  };
}

function secondsLabel(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return '';
  return `${Math.floor(ms / 1000)}s`;
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
  execution?: ExecutionOut;
}

export function WorkflowProgressCard({ wf, campaignId, execution }: Props) {
  const t = useTranslations('campaignsFeature.list');
  const tCommon = useTranslations('common');
  const tGate = useTranslations('executionMessages');
  const confirm = useConfirm();
  const { canExecute } = useResourcePermissions('campaigns');
  const { getStepTypeName } = useCampaignFlowI18n();
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [liveMirrorSerial, setLiveMirrorSerial] = useState<string | null>(() =>
    getCampaignMonitorLiveMirrorSerial()
  );

  const isActive =
    wf.status === 'RUNNING' ||
    wf.status === 'PAUSED' ||
    wf.status === 'paused_on_error';

  const executionId = useMemo(
    () =>
      wf.execution_id ||
      execution?.id ||
      resolveExecutionIdForWorkflow(
        wf.workflow_id,
        execution ? [execution] : []
      ),
    [wf.execution_id, wf.workflow_id, execution]
  );

  const serial = useMemo(() => {
    if (wf.device_serial) return wf.device_serial;
    const fromWorkflow = parseSerial(wf.workflow_id);
    if (!wf.workflow_id.startsWith('exec_')) return fromWorkflow;
    const cfg = (execution?.device_config ?? {}) as Record<string, unknown>;
    return String(cfg.device_serial ?? fromWorkflow);
  }, [wf.device_serial, wf.workflow_id, execution]);
  const verification = (execution?.meta?.account_verification ?? {}) as Record<
    string,
    unknown
  >;
  const fallbackAccountLabel = execution?.account_id
    ? `Account #${execution.account_id.slice(0, 8)}`
    : '';
  const verificationStatus = String(verification.status ?? '');

  const showLiveMirror = expanded && liveMirrorSerial === serial;

  useEffect(() => {
    return subscribeCampaignMonitorLiveMirror(setLiveMirrorSerial);
  }, []);

  useEffect(() => {
    if (expanded) return;
    releaseCampaignMonitorLiveMirror(serial);
  }, [expanded, serial]);

  useEffect(() => {
    return () => {
      releaseCampaignMonitorLiveMirror(serial);
    };
  }, [serial]);

  const scenarioId = wf.scenario_id || parseScenarioId(wf.workflow_id);
  const workflowCampaignId = wf.campaign_id || campaignId;
  const campaignLabel =
    wf.campaign_name || `#${workflowCampaignId.slice(0, 8)}`;
  const scenarioLabel =
    wf.scenario_name ||
    (wf.scenario_count && wf.scenario_count > 1
      ? t('monitorWorkflowScenarioCount', { count: wf.scenario_count })
      : scenarioId
        ? `#${scenarioId.slice(0, 8)}`
        : t('monitorWorkflowUnknownScenario'));

  // SSE only while expanded — N collapsed cards must not open N event streams.
  const eventStream = useExecutionEventStream(executionId, {
    enabled: isActive && !!executionId && expanded,
    workflowId: wf.workflow_id,
    deviceSerial: serial
  });
  const unifiedStepLog = eventStream.stepLog;
  const displaySerial = serial;
  const accountLabel = fallbackAccountLabel;
  const { data: orgScenarios } = useOrgScenarios();
  const scenarioNamesById = useMemo(() => {
    const map = new Map<string, string>();
    for (const scenario of orgScenarios ?? []) {
      map.set(scenario.id, scenario.name);
    }
    return map;
  }, [orgScenarios]);
  const activeRecovery = useMemo(
    () => detectActiveRecoveryFromEvents(eventStream.events, scenarioNamesById),
    [eventStream.events, scenarioNamesById]
  );
  const isRecoveryMode =
    wf.workflow_kind === 'recovery' || activeRecovery.active;

  const pollProgress = useWorkflowProgress(wf.workflow_id, isActive);
  const prog = mergeProgressSources(eventStream.progress, pollProgress.data);
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
  const rawMessage = prog?.message ?? '';
  const message = humanizeSessionGateMessage(rawMessage, tGate) ?? rawMessage;
  const runningElapsedMs =
    prog?.running_step === true ? (prog.current_step_elapsed_ms ?? 0) : 0;
  const runningElapsedLabel =
    runningElapsedMs > 0 ? `${Math.floor(runningElapsedMs / 1000)}s` : '';
  const activityId = prog?.current_activity_id ?? null;
  const activityLabel = compactActivityId(activityId);
  const activityStepId = prog?.current_step_activity_id ?? null;
  const activityPhase = prog?.current_phase ?? null;
  const sideEffectClass = prog?.side_effect_class ?? null;
  const activityAttempt =
    prog?.activity_attempt != null && prog.activity_attempt > 0
      ? prog.activity_attempt
      : null;
  const hasActivityProgress =
    !!activityId ||
    !!activityPhase ||
    !!sideEffectClass ||
    activityAttempt !== null;
  const activityState = prog?.activity_state ?? null;
  const stalledReason = prog?.stalled_reason ?? null;
  const stalledAfterLabel = secondsLabel(prog?.stalled_after_ms);
  const isActivityWarning =
    activityState === 'possibly_stalled' || activityState === 'timed_out';
  const activityStateLabel = activityState
    ? t(
        activityState === 'scheduled'
          ? 'monitorWfActivityStateScheduled'
          : activityState === 'running'
            ? 'monitorWfActivityStateRunning'
            : activityState === 'possibly_stalled'
              ? 'monitorWfActivityStatePossiblyStalled'
              : activityState === 'timed_out'
                ? 'monitorWfActivityStateTimedOut'
                : activityState === 'paused'
                  ? 'monitorWfActivityStatePaused'
                  : activityState === 'cancelled'
                    ? 'monitorWfActivityStateCancelled'
                    : 'monitorWfActivityStateIdle'
      )
    : '';
  const stalledReasonLabel = stalledReason
    ? t(
        stalledReason === 'no_worker_pickup_or_activity_heartbeat_gap'
          ? 'monitorWfStalledNoWorkerOrHeartbeat'
          : stalledReason === 'heartbeat_timeout_risk'
            ? 'monitorWfStalledHeartbeatTimeoutRisk'
            : stalledReason === 'long_io_action'
              ? 'monitorWfStalledLongIoAction'
              : stalledReason === 'long_read_action'
                ? 'monitorWfStalledLongReadAction'
                : 'monitorWfStalledLongDeviceAction'
      )
    : '';
  const loopIter =
    prog?.current_loop_iter != null && prog.current_loop_iter >= 0
      ? prog.current_loop_iter
      : prog?.loop_iteration != null && prog.loop_iteration >= 0
        ? prog.loop_iteration
        : null;
  const currentTrace = prog
    ? executionTraceFromRecord(prog as Record<string, unknown>)
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
            title={displaySerial}
          >
            {displaySerial}
          </span>
          <WorkflowScenarioModeBadge
            mode={isRecoveryMode ? 'recovery' : 'main'}
            scenarioName={activeRecovery.scenarioName}
          />
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

        <div className='mb-1.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 pl-[26px] text-[10px] text-muted-foreground'>
          <span
            className='min-w-0 truncate'
            title={wf.campaign_name || workflowCampaignId}
          >
            {campaignLabel}
          </span>
          <span className='text-muted-foreground/50'>/</span>
          <span
            className='min-w-0 truncate'
            title={wf.scenario_name || scenarioId || undefined}
          >
            {scenarioLabel}
          </span>
          {executionId && (
            <>
              <span className='text-muted-foreground/50'>/</span>
              <span className='font-mono'>
                {t('monitorWorkflowExecutionShort', {
                  id: executionId.slice(0, 8)
                })}
              </span>
            </>
          )}
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
          <>
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
              {runningElapsedLabel && (
                <span
                  className='rounded bg-muted px-1.5 py-0.5 font-mono text-[9px]'
                  title={prog?.current_step_started_at ?? undefined}
                >
                  {runningElapsedLabel}
                </span>
              )}
              {message && (
                <span className='flex-1 truncate italic' title={rawMessage}>
                  {message}
                </span>
              )}
            </div>
            <ExecutionTraceChips
              trace={currentTrace}
              className='mt-1 pl-[26px]'
              maxPathClassName='max-w-[220px] sm:max-w-[320px]'
            />
            {hasActivityProgress && (
              <div className='mt-1 flex min-w-0 flex-wrap items-center gap-1.5 pl-[26px] text-[9px] text-muted-foreground'>
                <span className='inline-flex min-w-0 max-w-full items-center gap-1 rounded border bg-background px-1.5 py-0.5'>
                  <Activity size={9} className='shrink-0' />
                  <span className='shrink-0 font-semibold'>
                    {t('monitorWfActivity')}
                  </span>
                  {activityLabel ? (
                    <span
                      className='min-w-0 truncate font-mono'
                      title={activityId ?? undefined}
                    >
                      {activityLabel}
                    </span>
                  ) : (
                    <span>{t('monitorWfActivityPending')}</span>
                  )}
                </span>
                {activityPhase && (
                  <span
                    className='rounded bg-blue-500/10 px-1.5 py-0.5 font-mono text-blue-700 dark:text-blue-300'
                    title={t('monitorWfActivityPhase')}
                  >
                    {activityPhase}
                  </span>
                )}
                {sideEffectClass && (
                  <span
                    className='rounded bg-amber-500/10 px-1.5 py-0.5 font-mono text-amber-700 dark:text-amber-300'
                    title={t('monitorWfActivitySideEffect')}
                  >
                    {sideEffectClass}
                  </span>
                )}
                {activityAttempt !== null && (
                  <span
                    className='rounded bg-muted px-1.5 py-0.5 font-mono'
                    title={t('monitorWfActivityAttempt')}
                  >
                    {t('monitorWfActivityAttemptShort', {
                      n: activityAttempt
                    })}
                  </span>
                )}
                {activityState && activityState !== 'idle' && (
                  <span
                    className={cn(
                      'rounded px-1.5 py-0.5 font-semibold',
                      isActivityWarning
                        ? 'bg-orange-500/10 text-orange-700 dark:text-orange-300'
                        : 'bg-muted text-muted-foreground'
                    )}
                    title={t('monitorWfActivityState')}
                  >
                    {activityStateLabel}
                  </span>
                )}
                {isActivityWarning && stalledReasonLabel && (
                  <span
                    className='inline-flex min-w-0 max-w-full items-center gap-1 rounded bg-orange-500/10 px-1.5 py-0.5 font-semibold text-orange-700 dark:text-orange-300'
                    title={stalledReason ?? undefined}
                  >
                    <AlertTriangle size={9} className='shrink-0' />
                    <span className='min-w-0 truncate'>
                      {stalledReasonLabel}
                    </span>
                    {stalledAfterLabel && (
                      <span className='shrink-0 font-mono'>
                        +{stalledAfterLabel}
                      </span>
                    )}
                  </span>
                )}
                {activityStepId && activityStepId !== activityId && (
                  <span
                    className='min-w-0 truncate font-mono'
                    title={activityStepId}
                  >
                    {compactActivityId(activityStepId)}
                  </span>
                )}
              </div>
            )}
          </>
        )}

        {accountLabel && (
          <div className='mt-1 flex items-center gap-1.5 pl-[26px] text-[9px] text-muted-foreground'>
            <span>{accountLabel}</span>
            {verificationStatus && (
              <span
                className={cn(
                  'rounded px-1.5 py-0.5 font-semibold',
                  verificationStatus === 'verified'
                    ? 'bg-green-500/15 text-green-600 dark:text-green-400'
                    : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                )}
              >
                {verificationStatus}
              </span>
            )}
          </div>
        )}

        {wf.status === 'FAILED' && message && (
          <p
            className='mt-1 truncate pl-[26px] text-[10px] text-destructive'
            title={rawMessage}
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
              {showLiveMirror ? (
                <div className='space-y-2'>
                  <div className='flex items-center justify-between gap-2'>
                    <p className='text-[10px] font-medium text-muted-foreground'>
                      {t('titleLivePreview')}
                    </p>
                    <Button
                      type='button'
                      size='sm'
                      variant='ghost'
                      className='h-6 gap-1 px-2 text-[10px]'
                      onClick={(e) => {
                        e.stopPropagation();
                        releaseCampaignMonitorLiveMirror(serial);
                      }}
                    >
                      <MonitorOff size={10} />
                      {t('monitorHideLiveMirror')}
                    </Button>
                  </div>
                  <DeviceControlEmbed
                    initialSerial={serial}
                    compact
                    hideStepMonitor
                    readOnlyPreview
                    forceStream
                  />
                </div>
              ) : (
                <div className='flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-muted/20 px-3 py-6 text-center'>
                  <p className='text-[11px] text-muted-foreground'>
                    {t('monitorLiveMirrorHint')}
                  </p>
                  <Button
                    type='button'
                    size='sm'
                    variant='outline'
                    className='h-7 gap-1.5 text-[11px]'
                    onClick={(e) => {
                      e.stopPropagation();
                      claimCampaignMonitorLiveMirror(serial);
                    }}
                  >
                    <MonitorPlay size={12} />
                    {t('titleLivePreview')}
                  </Button>
                </div>
              )}
            </div>
            <div className='min-w-0 flex-1 px-3 py-3'>
              <p className='mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                <List size={10} /> {t('monitorStepsHeading')}
              </p>
              <WorkflowStepList
                wf={wf}
                maxHeight='min(560px, calc(90dvh - 320px))'
                sseStepLog={unifiedStepLog}
                sseConnected={eventStream.connected}
                liveProgress={{
                  current_step: current,
                  total_steps: total,
                  current_step_type: stepType,
                  current_step_id: currentTrace?.stepId ?? null,
                  current_step_path: currentTrace?.stepPath ?? null,
                  current_loop_iter: loopIter,
                  reason_code: currentTrace?.reasonCode ?? null,
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
