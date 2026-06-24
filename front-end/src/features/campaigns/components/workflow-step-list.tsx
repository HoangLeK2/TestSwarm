'use client';

/**
 * Shared step-log display used by:
 *  - WorkflowProgressCard (campaign monitor, expanded section)
 *  - DeviceStepMonitor (device tile dialog)
 */

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Loader2,
  Wrench,
  XCircle
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { scenariosApi, executionsApi } from '../services/api';
import { useCampaignFlowI18n } from './flow-editor/flow-i18n';
import { useExecutionEventStream } from '../hooks/use-execution-event-stream';
import { useWorkflowProgress, useWorkflowSteps } from '../hooks/use-campaigns';
import {
  foldEventsToProgress,
  foldEventsToStepLog,
  deviceSerialFromWorkflowId
} from '../lib/execution-event-utils';
import {
  buildWorkflowStepRows,
  deriveWorkflowCursor,
  mergeStepLogEntries,
  normalizeTemporalStepLogEntry,
  resolveCurrentRootIndex,
  type WorkflowStepRowStatus
} from '../lib/workflow-step-list-model';
import type { ExecutionEventOut } from '../../device-farm/services/generated/DeviceFarmApi';
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

import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import {
  incidentEventLabelKey,
  isRecoveryIncidentEvent,
  resolveRecoveryScenarioName,
  shortDisplayId
} from '../lib/workflow-incident-display';
import type { IncidentEvent } from '../types';

function IncidentStepCard({
  incident,
  scenarioNamesById
}: {
  incident: IncidentEvent;
  scenarioNamesById: ReadonlyMap<string, string>;
}) {
  const t = useTranslations('campaignsFeature.list');
  const isRecovery = isRecoveryIncidentEvent(incident.event_type);
  const typeKey = incident.incident_type
    ? `monitorIncidentType.${incident.incident_type}`
    : 'monitorIncidentType.unknown';
  const outcomeKey = incident.outcome
    ? `monitorRecoveryOutcome.${incident.outcome}`
    : null;
  const recoveryName = isRecovery
    ? resolveRecoveryScenarioName(incident, scenarioNamesById)
    : '';
  const recoveryShortId =
    shortDisplayId(incident.recovery_scenario_id) ||
    shortDisplayId(incident.scenario_id);
  const showRecoveryId =
    recoveryName &&
    recoveryShortId &&
    recoveryName !== recoveryShortId &&
    !recoveryName.includes(recoveryShortId);

  return (
    <div
      className={cn(
        'rounded-md border px-2.5 py-2',
        isRecovery
          ? 'border-sky-500/30 bg-sky-500/10 text-sky-950 dark:text-sky-50'
          : 'border-amber-500/30 bg-amber-500/10 text-amber-950 dark:text-amber-100'
      )}
    >
      <div className='flex min-w-0 items-start gap-2'>
        {isRecovery ? (
          <Wrench size={12} className='mt-0.5 shrink-0' />
        ) : (
          <AlertCircle size={12} className='mt-0.5 shrink-0' />
        )}
        <div className='min-w-0 flex-1'>
          <div className='text-[10px] font-semibold leading-tight'>
            {t(incidentEventLabelKey(incident.event_type))}
          </div>
          {isRecovery && recoveryName ? (
            <div
              className='mt-0.5 truncate text-[11px] font-medium leading-tight'
              title={recoveryName}
            >
              {recoveryName}
              {showRecoveryId ? (
                <span className='ml-1 font-mono text-[10px] font-normal opacity-70'>
                  #{recoveryShortId}
                </span>
              ) : null}
            </div>
          ) : null}
          <div className='mt-1 flex flex-wrap items-center gap-1'>
            <Badge
              variant='outline'
              className={cn(
                'h-4 px-1.5 text-[9px] font-medium normal-case',
                isRecovery
                  ? 'border-sky-500/25 bg-background/60 text-sky-900 dark:text-sky-100'
                  : 'border-amber-500/25 bg-background/60 text-amber-900 dark:text-amber-100'
              )}
            >
              {t(typeKey)}
            </Badge>
            {incident.attempt != null ? (
              <span className='text-[9px] text-muted-foreground'>
                {t('monitorRecoveryAttempt', { attempt: incident.attempt })}
              </span>
            ) : null}
          </div>
          {(outcomeKey || incident.message) && (
            <div
              className={cn(
                'mt-1 text-[10px] leading-snug',
                isRecovery
                  ? 'text-sky-900/85 dark:text-sky-100/85'
                  : 'text-amber-900/85 dark:text-amber-100/85'
              )}
            >
              {outcomeKey ? t(outcomeKey) : null}
              {outcomeKey && incident.message ? ' · ' : null}
              {incident.message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

type StepCategory = 'app' | 'logic' | 'touch' | 'input' | 'key' | 'other';

const APP_STEP_TYPES = new Set([
  'launch_app',
  'stop_app',
  'clear_app',
  'wait_app',
  'open_url',
  'install_apk',
  'push_file',
  'pull_file',
  'scroll_down',
  'scroll_to'
]);
const LOGIC_STEP_TYPES = new Set([
  'if',
  'if_element',
  'if_variable',
  'break_if',
  'loop',
  'repeat',
  'repeat_until',
  'random_pick',
  'run_scenario',
  'wait',
  'wait_element',
  'wait_stable',
  'verify_screen',
  'assert_element',
  'dismiss_popup'
]);
const TOUCH_STEP_TYPES = new Set([
  'tap',
  'tap_ratio',
  'tap_position',
  'tap_selector',
  'long_tap_selector',
  'swipe_ratio',
  'double_tap',
  'pinch',
  'drag'
]);
const INPUT_STEP_TYPES = new Set([
  'input_text',
  'input_selector',
  'extract',
  'save_extraction',
  'extract_text_hierarchy',
  'extract_text_ocr',
  'extract_text_ai',
  'extract_screen_data',
  'set_variable',
  'set_var',
  'set_clipboard'
]);

function stepCategory(type: string): StepCategory {
  if (APP_STEP_TYPES.has(type)) return 'app';
  if (LOGIC_STEP_TYPES.has(type)) return 'logic';
  if (TOUCH_STEP_TYPES.has(type) || type.startsWith('tap')) return 'touch';
  if (INPUT_STEP_TYPES.has(type) || type.startsWith('extract')) return 'input';
  if (type === 'key' || type === 'key_back') return 'key';
  return 'other';
}

function stepTypeBadgeClass(
  type: string,
  state: 'running' | 'ok' | 'failed' | 'pending'
): string {
  if (state === 'running')
    return 'border-transparent bg-primary/15 text-primary';
  if (state === 'ok')
    return 'border-transparent bg-green-500/10 text-green-700 dark:text-green-400';
  if (state === 'failed')
    return 'border-transparent bg-destructive/10 text-destructive';

  const category = stepCategory(type);
  const pendingByCategory: Record<StepCategory, string> = {
    app: 'border-transparent bg-primary/10 text-primary/80',
    logic:
      'border-transparent bg-amber-500/10 text-amber-700 dark:text-amber-300',
    touch:
      'border-transparent bg-purple-500/10 text-purple-700 dark:text-purple-300',
    input:
      'border-transparent bg-green-500/10 text-green-700 dark:text-green-400',
    key: 'border-transparent bg-muted text-muted-foreground',
    other: 'border-transparent bg-muted text-muted-foreground'
  };
  return pendingByCategory[category];
}

function ProgressStat({
  label,
  value,
  tone
}: {
  label: string;
  value: string | number;
  tone?: 'primary' | 'success' | 'muted';
}) {
  return (
    <div className='rounded-md border bg-muted/20 px-2.5 py-2'>
      <p className='text-[9px] font-medium uppercase tracking-wide text-muted-foreground'>
        {label}
      </p>
      <p
        className={cn(
          'mt-0.5 text-sm font-semibold tabular-nums',
          tone === 'primary' && 'text-primary',
          tone === 'success' && 'text-green-600 dark:text-green-400',
          tone === 'muted' && 'text-muted-foreground'
        )}
      >
        {value}
      </p>
    </div>
  );
}

export function StepRow({
  index,
  stepDef,
  logEntry,
  isCurrentlyRunning,
  currentStepType,
  currentMessage,
  loopIter,
  isPending: _isPending,
  status,
  depth,
  branchLabel,
  isLast = false,
  scenarioNamesById
}: {
  index: number;
  stepDef?: FlowStep;
  logEntry?: StepLogEntry;
  isCurrentlyRunning: boolean;
  currentStepType: string;
  currentMessage: string;
  loopIter: number | null;
  isPending: boolean;
  status: WorkflowStepRowStatus;
  depth: number;
  branchLabel?: string;
  isLast?: boolean;
  scenarioNamesById: ReadonlyMap<string, string>;
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
  const isDone = status === 'completed' || status === 'failed';
  const isFailed = status === 'failed' || (isDone && logEntry?.ok === false);
  const isOk = status === 'completed';
  const msg = isCurrentlyRunning
    ? (logEntry?.message ?? currentMessage)
    : (logEntry?.message ?? '');
  const adbOutput = stepOutput(logEntry);
  const incidents = logEntry?.incidents ?? [];
  const badgeState = isCurrentlyRunning
    ? 'running'
    : isFailed
      ? 'failed'
      : isOk
        ? 'ok'
        : 'pending';
  const railLeft = 20 + depth * 16;

  return (
    <div className='relative' style={{ paddingLeft: railLeft }}>
      {depth > 0 ? (
        <div
          className='absolute left-3 top-0 w-px bg-border'
          style={{ bottom: isLast ? '50%' : 0 }}
        />
      ) : null}
      {!isLast ? (
        <div
          className='absolute bottom-0 top-[22px] w-px bg-border'
          style={{ left: depth > 0 ? 12 : 26 }}
        />
      ) : null}

      <div
        className={cn(
          'mb-0.5 mr-2 flex gap-2.5 rounded-lg px-2 py-1.5 text-[11px] transition-colors',
          isCurrentlyRunning && 'border border-primary bg-primary/5',
          isFailed && 'border border-destructive/30 bg-destructive/5'
        )}
      >
        <div className='relative mt-1 w-3.5 shrink-0'>
          {isFailed ? (
            <XCircle size={14} className='text-destructive' />
          ) : isCurrentlyRunning ? (
            <>
              <Loader2 size={14} className='animate-spin text-primary' />
              <span className='absolute -inset-1 rounded-full border border-primary/30' />
            </>
          ) : isOk ? (
            <CheckCircle2 size={14} className='text-green-500' />
          ) : (
            <Circle
              size={10}
              className='ml-0.5 mt-0.5 text-muted-foreground/40'
            />
          )}
        </div>

        <div className='min-w-0 flex-1'>
          <div className='mb-0.5 flex min-w-0 items-center gap-1.5'>
            <span
              className={cn(
                'w-4 shrink-0 text-[10px] tabular-nums',
                isCurrentlyRunning
                  ? 'font-bold text-primary'
                  : 'text-muted-foreground'
              )}
            >
              {index + 1}
            </span>
            {branchLabel ? (
              <Badge
                variant='outline'
                className='h-4 px-1.5 text-[9px] font-medium normal-case'
              >
                {t(branchLabel)}
              </Badge>
            ) : null}
            <span className='min-w-0 flex-1' />
            {type ? (
              <Badge
                className={cn(
                  'h-4 shrink-0 px-1.5 text-[9px] font-bold uppercase tracking-wide',
                  stepTypeBadgeClass(type, badgeState)
                )}
              >
                {getStepTypeName(type)}
              </Badge>
            ) : null}
          </div>

          <div
            className={cn(
              'truncate leading-tight',
              isCurrentlyRunning
                ? 'font-semibold text-foreground'
                : isFailed
                  ? 'font-semibold text-destructive'
                  : isOk
                    ? 'text-foreground'
                    : 'text-muted-foreground'
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
            <div
              className='truncate text-[10px] text-destructive/80'
              title={msg}
            >
              {msg}
            </div>
          )}
          {incidents.length > 0 && (
            <div className='mt-1.5 space-y-1 text-[10px]'>
              {incidents.map((incident, incidentIndex) => (
                <IncidentStepCard
                  key={`${incident.event_type}-${incidentIndex}`}
                  incident={incident}
                  scenarioNamesById={scenarioNamesById}
                />
              ))}
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
      </div>
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
  const parsedWorkflowId = parseWorkflowId(wf.workflow_id);
  const campaignId = wf.campaign_id || parsedWorkflowId.campaignId;
  const scenarioId =
    wf.scenario_id === '__sequence__'
      ? ''
      : wf.scenario_id || parsedWorkflowId.scenarioId;
  const executionId = wf.execution_id ?? undefined;
  const deviceSerial =
    wf.device_serial || deviceSerialFromWorkflowId(wf.workflow_id) || '';
  const parentProvidesEventFeed =
    sseStepLog !== undefined || liveProgress !== undefined;

  const internalEventStream = useExecutionEventStream(executionId, {
    enabled: isActive && !!executionId && !parentProvidesEventFeed,
    workflowId: wf.workflow_id,
    deviceSerial
  });

  const eventStepLog = parentProvidesEventFeed
    ? (sseStepLog ?? [])
    : internalEventStream.stepLog;

  const shouldPollEvents =
    isActive && !!executionId && !parentProvidesEventFeed;
  const { data: polledEvents } = useQuery({
    queryKey: ['execution-events', executionId],
    queryFn: () => executionsApi.listEvents(executionId!, { limit: 500 }),
    enabled: shouldPollEvents,
    staleTime: 2_000,
    refetchInterval: shouldPollEvents ? 3_000 : false,
    refetchOnWindowFocus: false
  });
  const polledEventStepLog = useMemo(
    () => foldEventsToStepLog(polledEvents?.items ?? []),
    [polledEvents?.items]
  );
  const mergedEventStepLog = useMemo(
    () => mergeStepLogEntries(eventStepLog, polledEventStepLog),
    [eventStepLog, polledEventStepLog]
  );

  const useEventSteps = mergedEventStepLog.length > 0;
  const shouldFetchStepLog = !useEventSteps;

  const { data: stepLog, isLoading: logLoading } = useWorkflowSteps(
    wf.workflow_id,
    shouldFetchStepLog,
    isActive
  );
  const eventProgress = parentProvidesEventFeed ? liveProgress : undefined;
  const allExecutionEvents = useMemo(() => {
    if (parentProvidesEventFeed) return [];
    const byId = new Map<string, ExecutionEventOut>();
    for (const ev of polledEvents?.items ?? []) {
      if (ev?.event_id) byId.set(ev.event_id, ev);
    }
    for (const ev of internalEventStream.events) {
      if (ev?.event_id) byId.set(ev.event_id, ev);
    }
    return Array.from(byId.values());
  }, [
    parentProvidesEventFeed,
    polledEvents?.items,
    internalEventStream.events
  ]);
  const eventDerivedProgress = useMemo(
    () =>
      allExecutionEvents.length > 0
        ? foldEventsToProgress(allExecutionEvents, wf.workflow_id, deviceSerial)
        : null,
    [allExecutionEvents, wf.workflow_id, deviceSerial]
  );
  const shouldPollProgress =
    isActive && !eventProgress && !eventDerivedProgress;
  const { data: polledProgress } = useWorkflowProgress(
    wf.workflow_id,
    shouldPollProgress
  );

  const { data: scenario, isLoading: scenarioLoading } = useQuery({
    queryKey: ['scenario-steps', campaignId, scenarioId],
    queryFn: () => scenariosApi.get(campaignId, scenarioId),
    enabled: !!campaignId && !!scenarioId,
    staleTime: 30_000
  });
  const { data: campaignScenarios, isLoading: campaignScenariosLoading } =
    useQuery({
      queryKey: ['scenario-steps-fallback', campaignId],
      queryFn: () => scenariosApi.list(campaignId),
      enabled: !!campaignId && !scenarioId && !wf.scenario_steps?.length,
      staleTime: 30_000
    });
  const { data: orgScenarios } = useOrgScenarios();
  const scenarioNamesById = useMemo(() => {
    const map = new Map<string, string>();
    for (const scenario of orgScenarios ?? []) {
      map.set(scenario.id, scenario.name);
    }
    return map;
  }, [orgScenarios]);

  if (
    scenarioLoading ||
    campaignScenariosLoading ||
    (!useEventSteps && logLoading)
  ) {
    return (
      <div className='flex items-center gap-2 py-4 text-xs text-muted-foreground'>
        <Loader2 size={12} className='animate-spin' />{' '}
        {t('monitorStepListLoading')}
      </div>
    );
  }

  const scenarioDefs: FlowStep[] = (() => {
    if (scenario?.steps?.length) return scenario.steps as FlowStep[];
    if (wf.scenario_steps?.length) return wf.scenario_steps as FlowStep[];
    const scenarios = campaignScenarios ?? [];
    if (scenarios.length === 1)
      return (scenarios[0]?.steps ?? []) as FlowStep[];
    return scenarios
      .filter((item) => (item.steps ?? []).length > 0)
      .map(
        (item) =>
          ({
            type: 'run_scenario',
            scenario_id: item.id,
            title: item.name,
            steps: item.steps ?? []
          }) as FlowStep
      );
  })();
  const temporalSteps: StepLogEntry[] = (stepLog?.steps ?? []).map((raw) =>
    normalizeTemporalStepLogEntry(raw as Record<string, unknown>)
  );
  const executedSteps: StepLogEntry[] = useEventSteps
    ? mergeStepLogEntries(mergedEventStepLog, temporalSteps)
    : temporalSteps;

  const progressSource =
    eventProgress ??
    eventDerivedProgress ??
    internalEventStream.progress ??
    polledProgress;
  const derivedCursor = deriveWorkflowCursor({
    executedSteps,
    isActive,
    fallbackCurrentStep: progressSource?.current_step ?? 0,
    fallbackStepType: progressSource?.current_step_type ?? '',
    fallbackMessage: progressSource?.message ?? ''
  });
  const current = resolveCurrentRootIndex({
    executedSteps,
    isActive,
    progressCurrentStep: progressSource?.current_step
  });
  const stepType =
    derivedCursor.currentStepType || progressSource?.current_step_type || '';
  const message = derivedCursor.message || progressSource?.message || '';
  const loopIter =
    progressSource?.loop_iteration != null && progressSource.loop_iteration >= 0
      ? progressSource.loop_iteration
      : null;
  const rows = buildWorkflowStepRows({
    scenarioSteps: scenarioDefs,
    executedSteps,
    currentRootIndex: current,
    isActive,
    isCompleted: wf.status === 'COMPLETED'
  });
  const total = rows.totalCount;
  const completed = wf.status === 'COMPLETED' ? total : rows.completedCount;
  const runningRow = rows.find((row) => row.status === 'running');
  const currentStepNumber = runningRow
    ? runningRow.flatIndex + 1
    : wf.status === 'COMPLETED'
      ? total
      : Math.min(completed + 1, total);
  const remaining = Math.max(total - completed - (runningRow ? 1 : 0), 0);
  const pct =
    total > 0
      ? Math.round((completed / total) * 100)
      : wf.status === 'COMPLETED'
        ? 100
        : 0;

  return (
    <div className='space-y-3'>
      <div className='space-y-2'>
        <div className='flex items-center justify-between gap-2 text-[10px] text-muted-foreground'>
          <span className='font-medium'>{t('monitorProgressLabel')}</span>
          <span className='shrink-0 tabular-nums'>
            {completed}/{total}
          </span>
        </div>
        <Progress
          value={pct}
          className={cn(
            'h-2',
            wf.status === 'FAILED' && '[&>div]:bg-destructive',
            wf.status === 'PAUSED' && '[&>div]:bg-amber-500',
            wf.status === 'COMPLETED' && '[&>div]:bg-green-500'
          )}
        />
        <div className='grid grid-cols-3 gap-2'>
          <ProgressStat
            label={t('monitorStatCurrentStep')}
            value={total > 0 ? currentStepNumber : '—'}
            tone='primary'
          />
          <ProgressStat
            label={t('monitorStatCompleted')}
            value={completed}
            tone='success'
          />
          <ProgressStat
            label={t('monitorStatRemaining')}
            value={remaining}
            tone='muted'
          />
        </div>
      </div>

      {rows.length > 0 ? (
        <div>
          <div className='overflow-y-auto py-1' style={{ maxHeight }}>
            {rows.map((row, rowIndex) => {
              const isCurrentlyRunning = row.status === 'running';
              return (
                <StepRow
                  key={row.pathKey}
                  index={row.flatIndex}
                  stepDef={row.step}
                  logEntry={row.logEntry}
                  isCurrentlyRunning={isCurrentlyRunning}
                  currentStepType={stepType}
                  currentMessage={message}
                  loopIter={loopIter}
                  isPending={row.status === 'pending'}
                  status={row.status}
                  depth={row.depth}
                  branchLabel={row.branchLabel}
                  isLast={rowIndex === rows.length - 1}
                  scenarioNamesById={scenarioNamesById}
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
            count: completed
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
