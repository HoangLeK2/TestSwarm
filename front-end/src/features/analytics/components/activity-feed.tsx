'use client';

import { useCallback, useMemo, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import Link from 'next/link';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  ExternalLink,
  Loader2,
  LogIn,
  MousePointerClick,
  FileText,
  ListChecks,
  MessageSquare,
  PlayCircle,
  Shield,
  Smartphone,
  Wifi,
  WifiOff,
  XCircle
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Heading } from '@/components/ui/heading';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { useExecutionTaskLog } from '@/features/campaigns/hooks/use-campaigns';
import type { ExecutionTaskLogStep } from '@/features/campaigns/types';
import { useActivityLog } from '../hooks/use-activity-log';
import type { ActivityLogItem } from '../services/api';
import { activityLogDeepLink } from '../lib/activity-deep-link';
import {
  DEDICATED_ACTIVITY_TITLE_ACTIONS,
  resolveActivityActionLabel,
  resolveDedicatedActivityTitle,
  resolveDomainActivityDescription
} from '../lib/activity-action-labels';
import { triggerBlobDownload } from '@/features/content/lib/download';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

function exportActivitiesCsv(
  activities: ActivityLogItem[],
  filename: string
): void {
  const header = ['id', 'action', 'created_at', 'device_serial', 'details'];
  const rows = activities.map((item) =>
    [
      item.id,
      item.action,
      item.created_at,
      item.device_serial ?? '',
      JSON.stringify(item.details ?? {})
    ]
      .map((v) => `"${String(v)}"`)
      .join(',')
  );
  const csv = [header.join(','), ...rows].join('\n');
  triggerBlobDownload(
    new Blob([csv], { type: 'text/csv;charset=utf-8' }),
    filename
  );
}

const ACTION_ICON = {
  'device.connect': Wifi,
  'device.disconnect': WifiOff,
  'device.error': AlertTriangle,
  'task.done': CheckCircle2,
  'task.failed': XCircle,
  'campaign.run': PlayCircle,
  'campaign.complete': CheckCircle2,
  'schedule.triggered': Clock
} as const;

const USER_OPERATION_LABEL_KEY: Record<string, string> = {
  '/api/devices/{serial}/interrupt': 'device_interrupt',
  '/api/devices/{serial}/scrcpy/attach': 'device_screen_attach',
  '/api/devices/{serial}/scrcpy/detach': 'device_screen_detach',
  '/api/devices/{device_id}/bootstrap': 'device_bootstrap',
  '/api/devices/{device_id}/restart-u2': 'device_restart_u2',
  '/api/devices/{device_id}/restart-atx': 'device_restart_atx',
  '/api/devices/{device_id}/restart-scrcpy': 'device_restart_scrcpy',
  '/api/campaigns/{campaign_id}/pause': 'campaign_pause',
  '/api/campaigns/{campaign_id}/resume': 'campaign_resume',
  '/api/campaigns/{campaign_id}/cancel': 'campaign_cancel',
  '/api/schedules/{schedule_id}/run-now': 'schedule_run_now',
  '/api/schedules/{schedule_id}/toggle': 'schedule_toggle'
};

function actionTone(action: string) {
  if (action.startsWith('user.')) return 'text-sky-500';
  if (
    action.endsWith('.failed') ||
    action.includes('cancelled') ||
    action.includes('run_failed') ||
    action.includes('dlq.opened') ||
    action.includes('rejected') ||
    action.includes('replay') ||
    action.includes('denied') ||
    action === 'device.disconnect' ||
    action === 'device.error' ||
    action === 'device.dead'
  ) {
    return 'text-destructive';
  }
  if (
    action.endsWith('.done') ||
    action.endsWith('.complete') ||
    action.endsWith('.success') ||
    action === 'device.connect' ||
    action === 'ws.connected' ||
    action === 'auth.refresh'
  ) {
    return 'text-emerald-500';
  }
  if (action.startsWith('auth.') || action.startsWith('ws.')) {
    return 'text-primary';
  }
  return 'text-primary';
}

function formatDate(value: string, locale: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(locale, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
}

function getActionLabel(action: string, t: ReturnType<typeof useTranslations>) {
  return resolveActivityActionLabel(action, t);
}

function getReasonLabel(reason: string, t: ReturnType<typeof useTranslations>) {
  if (!reason) return '';
  if (reason === 'unknown') return t('reasonLabels.unknown');
  if (reason === 'hello_timeout') return t('reasonLabels.hello_timeout');
  if (reason === 'busy_state') return t('reasonLabels.busy_state');
  if (reason === 'scenario_active') return t('reasonLabels.scenario_active');
  if (reason.startsWith('ws_closed')) return t('reasonLabels.ws_closed');
  if (reason.startsWith('ws_error')) return t('reasonLabels.ws_error');
  return reason;
}

function nestedString(value: unknown, key: string) {
  if (!value || typeof value !== 'object') return '';
  const record = value as Record<string, unknown>;
  const child = record[key];
  return typeof child === 'string' ? child : '';
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value !== 'string') continue;
    const trimmed = value.trim();
    if (trimmed) return trimmed;
  }
  return null;
}

function executionIdForActivity(item: ActivityLogItem): string | null {
  if (item.entity_type === 'execution') {
    return firstText(item.entity_id);
  }
  const details = item.details ?? {};
  return firstText(
    details.execution_id,
    details.executionId,
    nestedString(details.path_params, 'execution_id'),
    nestedString(details.query_params, 'execution_id')
  );
}

function shouldShowTaskLog(item: ActivityLogItem): boolean {
  if (!executionIdForActivity(item)) return false;
  return (
    item.entity_type === 'execution' ||
    item.action.startsWith('execution.') ||
    item.action.startsWith('campaign.') ||
    item.action.startsWith('scenario.') ||
    item.action.startsWith('task.')
  );
}

function getUserOperationLabel(
  item: ActivityLogItem,
  t: ReturnType<typeof useTranslations>
) {
  const route = item.route_template ?? '';
  const labelKey = USER_OPERATION_LABEL_KEY[route];
  if (labelKey) {
    return t(
      `operationLabels.${labelKey}` as 'operationLabels.device_interrupt'
    );
  }
  return t('operationLabels.generic');
}

function getOutcomeLabel(
  outcome: string | null | undefined,
  t: ReturnType<typeof useTranslations>
) {
  if (outcome === 'success') return t('outcomeLabels.success');
  if (outcome === 'rejected') return t('outcomeLabels.rejected');
  if (outcome === 'error') return t('outcomeLabels.error');
  return '';
}

function formatDurationMs(ms: number, t: ReturnType<typeof useTranslations>) {
  if (ms >= 1000) {
    return t('duration', { seconds: Math.round(ms / 1000) });
  }
  return t('durationMs', { ms });
}

function getActivityTitle(
  item: ActivityLogItem,
  t: ReturnType<typeof useTranslations>
) {
  const details = item.details ?? {};
  const serial = item.device_serial ? String(item.device_serial) : '';
  const deviceName =
    (details.device_name as string | undefined) ??
    (details.deviceName as string | undefined) ??
    (details.alias as string | undefined) ??
    (details.name as string | undefined);
  const deviceModel = [details.brand, details.model].filter(Boolean).join(' ');
  const deviceLabel =
    (deviceName || '').trim() ||
    (deviceModel || '').trim() ||
    serial ||
    t('unknownDevice');
  const taskName = String(details.name ?? t('task'));
  if (item.action.startsWith('user.')) {
    return getUserOperationLabel(item, t);
  }

  switch (item.action) {
    case 'device.connect':
      return t('titles.deviceConnect', { device: deviceLabel });
    case 'device.disconnect':
      return t('titles.deviceDisconnect', { device: deviceLabel });
    case 'device.error':
      return t('titles.deviceError', { device: deviceLabel });
    case 'task.done':
      return t('titles.taskDone', { task: taskName });
    case 'task.failed':
      return t('titles.taskFailed', { task: taskName });
    case 'campaign.run':
      return t('titles.campaignRun');
    case 'campaign.complete':
      return t('titles.campaignComplete');
    case 'schedule.triggered':
      return t('titles.scheduleTriggered');
    case 'auth.login.success':
      return t('titles.authLoginSuccess');
    case 'auth.login.failed':
      return t('titles.authLoginFailed');
    case 'auth.login.org_disabled':
      return t('titles.authLoginOrgDisabled');
    case 'auth.logout':
      return t('titles.authLogout');
    case 'auth.refresh':
      return t('titles.authRefresh');
    case 'auth.refresh.replay_attempt':
      return t('titles.authRefreshReplay');
    case 'ws.connected':
      return t('titles.wsConnected');
    case 'ws.auth.rejected':
      return t('titles.wsAuthRejected');
    default: {
      const dedicated = resolveDedicatedActivityTitle(item, t);
      if (dedicated) return dedicated;
      return getActionLabel(item.action, t);
    }
  }
}

function getActivityCategoryBadge(
  item: ActivityLogItem,
  title: string,
  t: ReturnType<typeof useTranslations>
): string | null {
  if (item.action.startsWith('user.')) {
    const generic = t('operationLabels.generic');
    const operation = getUserOperationLabel(item, t);
    if (operation === generic) return null;
    const category = t('actionLabels.user_action');
    return category === title ? null : category;
  }

  if (!DEDICATED_ACTIVITY_TITLE_ACTIONS.has(item.action)) {
    return null;
  }

  const category = getActionLabel(item.action, t);
  return category === title ? null : category;
}

function getActivityIcon(action: string) {
  if (action.startsWith('user.')) return MousePointerClick;
  if (action.startsWith('auth.') || action.startsWith('account.')) {
    return action.includes('success') || action.includes('refresh')
      ? LogIn
      : Shield;
  }
  if (action.startsWith('ws.')) return Wifi;
  if (action.startsWith('scenario.')) return FileText;
  if (action.startsWith('execution.') || action.startsWith('campaign.')) {
    return PlayCircle;
  }
  if (action.startsWith('schedule.')) return Clock;
  if (action.includes('dlq') || action.endsWith('.failed')) {
    return AlertTriangle;
  }
  return ACTION_ICON[action as keyof typeof ACTION_ICON] ?? Smartphone;
}

function taskStepStatusClass(status: string): string {
  const normalized = status.toLowerCase();
  if (
    normalized === 'completed' ||
    normalized === 'success' ||
    normalized === 'passed'
  ) {
    return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
  }
  if (normalized === 'failed' || normalized === 'error') {
    return 'border-destructive/20 bg-destructive/10 text-destructive';
  }
  if (normalized === 'running' || normalized === 'in_progress') {
    return 'border-blue-500/20 bg-blue-500/10 text-blue-700 dark:text-blue-300';
  }
  return 'border-border bg-muted text-muted-foreground';
}

function taskStepStatusIcon(status: string) {
  const normalized = status.toLowerCase();
  if (
    normalized === 'completed' ||
    normalized === 'success' ||
    normalized === 'passed'
  ) {
    return <CheckCircle2 className='size-3.5' />;
  }
  if (normalized === 'failed' || normalized === 'error') {
    return <XCircle className='size-3.5' />;
  }
  if (normalized === 'running' || normalized === 'in_progress') {
    return <Clock className='size-3.5' />;
  }
  return <Clock className='size-3.5' />;
}

function taskStepStatusLabel(
  status: string,
  t: ReturnType<typeof useTranslations>
): string {
  const normalized = status.toLowerCase();
  if (
    normalized === 'completed' ||
    normalized === 'success' ||
    normalized === 'passed'
  ) {
    return t('taskLogStatus.completed');
  }
  if (normalized === 'failed' || normalized === 'error') {
    return t('taskLogStatus.failed');
  }
  if (normalized === 'running' || normalized === 'in_progress') {
    return t('taskLogStatus.running');
  }
  return t('taskLogStatus.pending');
}

function taskStepTypeLabel(
  stepType: string | null | undefined,
  t: ReturnType<typeof useTranslations>
): string {
  if (stepType === 'run_scenario') return t('taskLogStepRunScenario');
  if (stepType === 'if_variable') return t('taskLogStepIfVariable');
  if (stepType === 'facebook_session_gate') {
    return t('taskLogStepFacebookSessionGate');
  }
  if (!stepType) return t('taskLogStepFallback');
  return stepType.replaceAll('_', ' ');
}

function friendlyStepCause(
  cause: string,
  t: ReturnType<typeof useTranslations>
): string {
  const normalized = cause.trim();
  if (normalized === 'if_variable: then branch failed') {
    return t('taskLogCauseIfThenFailed');
  }
  if (
    normalized ===
    'facebook_session_gate failed: Facebook session gate requires an execution account'
  ) {
    return t('taskLogCauseMissingExecutionAccount');
  }
  return normalized
    .replace(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
      ''
    )
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function taskStepMessage(
  step: ExecutionTaskLogStep,
  t: ReturnType<typeof useTranslations>
): string {
  const message = step.message?.trim();
  if (!message) return '';

  const completedMatch = message.match(
    /^run_scenario:\s*'[^']+'\s*completed\s*\((\d+)\s+steps?\)$/i
  );
  if (completedMatch?.[1]) {
    return t('taskLogMessageScenarioCompleted', {
      count: Number(completedMatch[1])
    });
  }

  const failedSubScenarioMatch = message.match(
    /^run_scenario:\s*sub-scenario\s*'[^']+'\s*failed\s*—\s*(.+)$/i
  );
  if (failedSubScenarioMatch?.[1]) {
    return t('taskLogMessageSubScenarioFailed', {
      cause: friendlyStepCause(failedSubScenarioMatch[1], t)
    });
  }

  return friendlyStepCause(message, t);
}

function ActivityTaskStepRow({ step }: { step: ExecutionTaskLogStep }) {
  const t = useTranslations('analyticsFeature.activity');
  const stepTitle = taskStepTypeLabel(step.step_type, t);
  const stepMessage = taskStepMessage(step, t);
  const statusLabel = taskStepStatusLabel(step.status, t);
  return (
    <li className='grid grid-cols-[1.75rem_minmax(0,1fr)_auto] gap-3 px-4 py-3'>
      <div
        className={cn(
          'mt-0.5 flex size-6 items-center justify-center rounded-full border',
          taskStepStatusClass(step.status)
        )}
      >
        {taskStepStatusIcon(step.status)}
      </div>
      <div className='min-w-0 space-y-1'>
        <div className='flex min-w-0 flex-wrap items-center gap-2'>
          <p className='truncate text-sm font-medium text-foreground'>
            {stepTitle}
          </p>
          <span className='text-[11px] text-muted-foreground'>
            {t('taskLogStepNumber', { index: step.step_index + 1 })}
          </span>
        </div>
        {stepMessage ? (
          <p
            className='line-clamp-2 text-xs leading-relaxed text-muted-foreground'
            title={stepMessage}
          >
            {stepMessage}
          </p>
        ) : null}
      </div>
      <Badge
        variant='outline'
        className={cn(
          'h-6 whitespace-nowrap px-2 text-[10px] font-medium',
          taskStepStatusClass(step.status)
        )}
      >
        {statusLabel}
      </Badge>
    </li>
  );
}

function ActivityTaskLogPreview({
  executionId,
  expanded
}: {
  executionId: string;
  expanded: boolean;
}) {
  const tActivity = useTranslations('analyticsFeature.activity');
  const tCampaign = useTranslations('campaignsFeature.list');
  const taskLog = useExecutionTaskLog(executionId, expanded, false);
  const summary = taskLog.data?.summary;
  const counters = summary?.counters ?? {};
  const failedStep = taskLog.data?.steps.find((step) =>
    ['failed', 'error'].includes(step.status.toLowerCase())
  );
  const context = taskLog.data?.context;
  const deviceLabel =
    context?.device_name?.trim() ||
    context?.device_serial?.trim() ||
    tActivity('taskLogUnknown');
  const accountLabel =
    context?.account_label?.trim() ||
    context?.account_platform?.trim() ||
    tActivity('taskLogNoAccount');
  const totalSteps = summary?.total_steps ?? taskLog.data?.steps.length ?? 0;
  const completedSteps = summary?.completed_steps ?? 0;
  const failedSteps = summary?.failed_steps ?? 0;
  const runningSteps = summary?.running_steps ?? 0;
  const visibleCounters = (
    ['matched', 'liked', 'commented', 'skipped'] as const
  ).filter((key) => Number(counters[key] ?? 0) > 0);

  if (!expanded) return null;

  return (
    <div className='mb-4 ml-10 mr-4 overflow-hidden rounded-md border bg-muted/20'>
      <div className='flex min-w-0 flex-wrap items-start justify-between gap-3 border-b bg-background px-4 py-3'>
        <div className='flex min-w-0 gap-3'>
          <div className='flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary'>
            <ListChecks className='size-4' />
          </div>
          <div className='min-w-0'>
            <p className='truncate text-sm font-semibold'>
              {tActivity('taskLogTitle')}
            </p>
            <p className='mt-0.5 text-xs text-muted-foreground'>
              {tActivity('taskLogSubtitle', {
                total: totalSteps,
                completed: completedSteps,
                failed: failedSteps
              })}
            </p>
            <div className='mt-2 flex min-w-0 flex-wrap gap-1.5'>
              <span className='inline-flex min-w-0 items-center gap-1 rounded border bg-muted px-2 py-1 text-[11px] text-muted-foreground'>
                <Smartphone className='size-3 shrink-0' />
                <span className='truncate'>
                  {tCampaign('monitorTaskLogDevice')}: {deviceLabel}
                </span>
              </span>
              <span className='inline-flex min-w-0 items-center gap-1 rounded border bg-muted px-2 py-1 text-[11px] text-muted-foreground'>
                <Shield className='size-3 shrink-0' />
                <span className='truncate'>
                  {tCampaign('monitorTaskLogAccount')}: {accountLabel}
                </span>
              </span>
            </div>
          </div>
        </div>
        {taskLog.isFetching ? (
          <Badge variant='secondary' className='h-6 gap-1 text-[10px]'>
            <Loader2 className='size-3 animate-spin' />
            {tActivity('taskLogRefreshing')}
          </Badge>
        ) : taskLog.data?.status ? (
          <Badge
            variant='outline'
            className={cn(
              'h-6 px-2 text-[10px]',
              taskStepStatusClass(taskLog.data.status)
            )}
          >
            {taskStepStatusLabel(taskLog.data.status, tActivity)}
          </Badge>
        ) : null}
      </div>

      {taskLog.isError ? (
        <p className='px-3 py-4 text-xs text-destructive'>
          {formatFarmApiError(
            taskLog.error,
            tCampaign('monitorTaskLogFailedToLoad')
          )}
        </p>
      ) : taskLog.isLoading ? (
        <p className='px-3 py-4 text-xs text-muted-foreground'>
          {tCampaign('monitorTaskLogLoading')}
        </p>
      ) : !taskLog.data?.steps.length ? (
        <p className='px-3 py-4 text-xs text-muted-foreground'>
          {tCampaign('monitorTaskLogEmpty')}
        </p>
      ) : (
        <>
          <div className='grid grid-cols-2 gap-2 border-b bg-background px-4 py-3 sm:grid-cols-4'>
            {(['completed', 'running', 'failed', 'total'] as const).map(
              (key) => {
                const value =
                  key === 'completed'
                    ? completedSteps
                    : key === 'running'
                      ? runningSteps
                      : key === 'failed'
                        ? failedSteps
                        : totalSteps;
                return (
                  <div key={key} className='rounded-md border px-3 py-2'>
                    <p className='text-[11px] text-muted-foreground'>
                      {tCampaign(`runHistorySummary.${key}`)}
                    </p>
                    <p className='mt-0.5 text-base font-semibold text-foreground'>
                      {(value ?? 0).toLocaleString()}
                    </p>
                  </div>
                );
              }
            )}
          </div>

          {failedStep ? (
            <div className='flex gap-2 border-b bg-destructive/5 px-4 py-3 text-xs text-destructive'>
              <AlertTriangle className='mt-0.5 size-4 shrink-0' />
              <div className='min-w-0'>
                <p className='font-medium'>{tActivity('taskLogFailure')}</p>
                <p className='mt-0.5 break-words text-destructive/80'>
                  {taskStepMessage(failedStep, tActivity) ||
                    taskStepTypeLabel(failedStep.step_type, tActivity)}
                </p>
              </div>
            </div>
          ) : null}

          <div className='flex flex-wrap gap-1.5 border-b bg-background px-4 py-2 text-[11px]'>
            {(visibleCounters.length
              ? visibleCounters
              : (['matched'] as const)
            ).map((key) => (
              <span
                key={key}
                className='inline-flex items-center gap-1 rounded border bg-muted px-2 py-1 text-muted-foreground'
              >
                {key === 'commented' ? (
                  <MessageSquare className='size-3' />
                ) : null}
                {tCampaign(`monitorTaskLogCounter.${key}`)}:{' '}
                <b className='font-semibold text-foreground'>
                  {Number(counters[key] ?? 0)}
                </b>
              </span>
            ))}
            {taskLog.data.has_more_steps ? (
              <span className='inline-flex items-center rounded border bg-muted px-2 py-1 text-muted-foreground'>
                {tCampaign('monitorTaskLogBounded')}
              </span>
            ) : null}
          </div>

          <ol className='max-h-[22rem] divide-y overflow-y-auto bg-background'>
            {taskLog.data.steps.map((step) => (
              <ActivityTaskStepRow key={step.id} step={step} />
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

function resolveDeviceDisplay(item: ActivityLogItem): string {
  if (item.device_display?.trim()) return item.device_display.trim();
  const details = item.details ?? {};
  const stored = details.device_label;
  if (typeof stored === 'string' && stored.trim()) return stored.trim();
  if (item.device_serial?.trim()) return item.device_serial.trim();
  const pathParams = details.path_params;
  const serial = nestedString(pathParams, 'serial');
  if (serial) return serial;
  return '';
}

function securityContextLine(
  item: ActivityLogItem,
  details: Record<string, unknown>,
  t: ReturnType<typeof useTranslations>
) {
  const parts: string[] = [];
  if (item.user_name?.trim()) {
    parts.push(t('performedBy', { user: item.user_name.trim() }));
  }
  const ip =
    (typeof details.ip === 'string' ? details.ip : '') ||
    (item.ip_address?.trim() ?? '');
  if (ip) parts.push(t('ipLine', { ip }));
  return parts.join(' · ');
}

function getActivityDescription(
  item: ActivityLogItem,
  t: ReturnType<typeof useTranslations>
) {
  const details = item.details ?? {};
  if (
    item.action.startsWith('auth.') ||
    item.action.startsWith('ws.') ||
    item.action.startsWith('account.') ||
    item.action.startsWith('admin.')
  ) {
    return securityContextLine(item, details, t);
  }
  if (
    item.action.startsWith('campaign.') ||
    item.action.startsWith('execution.') ||
    item.action.startsWith('scenario.') ||
    item.action.startsWith('session.') ||
    item.action.startsWith('schedule.')
  ) {
    const domainLine = resolveDomainActivityDescription(item, t, (serial) =>
      t('deviceSerial', { serial })
    );
    if (domainLine) return domainLine;
  }
  if (item.action.startsWith('user.')) {
    const parts = [];
    const deviceLabel = resolveDeviceDisplay(item);
    const pathParams = details.path_params;
    const hasDeviceRef = Boolean(
      nestedString(pathParams, 'serial') ||
        nestedString(pathParams, 'device_id') ||
        item.device_serial ||
        item.entity_id
    );
    const outcome = getOutcomeLabel(item.outcome, t);
    if (deviceLabel) {
      parts.push(t('deviceLine', { device: deviceLabel }));
    } else if (hasDeviceRef) {
      parts.push(t('deviceLine', { device: t('unknownDevice') }));
    }
    if (item.user_name?.trim()) {
      parts.push(t('performedBy', { user: item.user_name.trim() }));
    }
    if (outcome) parts.push(outcome);
    if (typeof item.duration_ms === 'number') {
      parts.push(formatDurationMs(item.duration_ms, t));
    }
    return parts.join(' · ');
  }
  if (item.action === 'device.disconnect' || item.action === 'device.error') {
    const reason = getReasonLabel(String(details.reason ?? ''), t);
    if (item.device_serial) {
      return reason
        ? `${t('deviceSerial', { serial: String(item.device_serial) })} · ${reason}`
        : t('deviceSerial', { serial: String(item.device_serial) });
    }
    return reason;
  }
  if (item.action === 'device.connect' && item.device_serial) {
    return t('deviceSerial', { serial: String(item.device_serial) });
  }
  if (item.action === 'task.done' || item.action === 'task.failed') {
    const parts = [];
    if (item.device_serial)
      parts.push(t('deviceSerial', { serial: String(item.device_serial) }));
    if (typeof details.duration_seconds === 'number') {
      parts.push(
        t('duration', { seconds: Math.round(details.duration_seconds) })
      );
    }
    if (item.action === 'task.failed' && details.error)
      parts.push(String(details.error));
    return parts.join(' · ');
  }
  return item.device_serial
    ? t('deviceSerial', { serial: String(item.device_serial) })
    : '';
}

function ActivityRow({
  item,
  locale
}: {
  item: ActivityLogItem;
  locale: string;
}) {
  const t = useTranslations('analyticsFeature.activity');
  const [expandedTaskLog, setExpandedTaskLog] = useState(false);
  const Icon = getActivityIcon(item.action);
  const title = getActivityTitle(item, t);
  const categoryBadge = getActivityCategoryBadge(item, title, t);
  const description = getActivityDescription(item, t);
  const deepLink = activityLogDeepLink(item);
  const taskLogExecutionId = executionIdForActivity(item);
  const hasTaskLog = Boolean(taskLogExecutionId && shouldShowTaskLog(item));
  const rowClass =
    'flex gap-3 border-b px-4 py-3 transition-colors last:border-0 min-h-[3.25rem]';

  const inner = (
    <>
      <div className='flex size-7 shrink-0 items-center justify-center rounded-md bg-muted'>
        <Icon size={15} className={actionTone(item.action)} />
      </div>
      <div className='min-w-0 flex-1'>
        <div className='flex items-start justify-between gap-3'>
          <div className='min-w-0 flex-1 space-y-0.5'>
            <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
              <p className='break-words text-sm font-medium leading-snug'>
                {title}
              </p>
              {categoryBadge ? (
                <Badge variant='secondary' className='shrink-0 text-[10px]'>
                  {categoryBadge}
                </Badge>
              ) : null}
            </div>
            <p
              className={
                description
                  ? 'break-words text-[11px] leading-relaxed text-muted-foreground'
                  : 'select-none text-[11px] leading-relaxed text-transparent'
              }
              aria-hidden={!description}
            >
              {description || '\u00a0'}
            </p>
          </div>
          <time
            dateTime={item.created_at}
            className='shrink-0 whitespace-nowrap pt-0.5 text-xs tabular-nums text-muted-foreground'
          >
            {formatDate(item.created_at, locale)}
          </time>
        </div>
      </div>
    </>
  );

  if (hasTaskLog && taskLogExecutionId) {
    return (
      <div className='border-b last:border-0'>
        <div className='flex min-h-[3.25rem] gap-3 px-4 py-3'>{inner}</div>
        <div className='mb-3 ml-10 mr-4 flex flex-wrap items-center gap-2'>
          <Button
            variant='outline'
            size='sm'
            className='h-7 px-2 text-xs'
            aria-expanded={expandedTaskLog}
            onClick={() => setExpandedTaskLog((value) => !value)}
          >
            {expandedTaskLog ? (
              <ChevronDown className='size-3.5' />
            ) : (
              <ChevronRight className='size-3.5' />
            )}
            {expandedTaskLog ? t('taskLogHide') : t('taskLogShow')}
          </Button>
          {deepLink ? (
            <Button
              asChild
              variant='ghost'
              size='sm'
              className='h-7 px-2 text-xs'
            >
              <Link href={deepLink}>
                <ExternalLink className='size-3.5' />
                {t('taskLogOpenRunHistory')}
              </Link>
            </Button>
          ) : null}
        </div>
        <ActivityTaskLogPreview
          executionId={taskLogExecutionId}
          expanded={expandedTaskLog}
        />
      </div>
    );
  }

  if (deepLink) {
    return (
      <Link href={deepLink} className={`${rowClass} hover:bg-muted/40`}>
        {inner}
      </Link>
    );
  }

  return <div className={rowClass}>{inner}</div>;
}

const PAGE_SIZE = 50;

const ACTION_FILTER_OPTIONS = [
  'all',
  'device.connect',
  'device.disconnect',
  'device.error',
  'campaign.run',
  'campaign.complete',
  'campaign.dispatched',
  'execution.started',
  'execution.completed',
  'execution.failed',
  'execution.cancelled',
  'task.done',
  'task.failed',
  'schedule.triggered'
] as const;

export function ActivityFeed({ embedded = false }: { embedded?: boolean }) {
  const tPage = useTranslations('analyticsFeature.dashboard');
  const tActivity = useTranslations('analyticsFeature.activity');
  const locale = useLocale();
  const [actionFilter, setActionFilter] = useState<string>('all');
  const [deviceSerial, setDeviceSerial] = useState('');
  const [page, setPage] = useState(0);

  const query = useMemo(
    () => ({
      action: actionFilter === 'all' ? undefined : actionFilter,
      device_serial: deviceSerial.trim() || undefined,
      offset: page * PAGE_SIZE,
      limit: PAGE_SIZE
    }),
    [actionFilter, deviceSerial, page]
  );

  const { data, isLoading, error, refetch, isFetching } = useActivityLog(query);
  const activities = data?.activities ?? [];
  const total = data?.total ?? activities.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const resetFilters = useCallback(() => {
    setActionFilter('all');
    setDeviceSerial('');
    setPage(0);
  }, []);

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        {embedded ? (
          <div className='space-y-0.5'>
            <p className='text-sm font-medium'>{tActivity('title')}</p>
            <p className='text-xs text-muted-foreground'>
              {tActivity('subtitle')}
            </p>
          </div>
        ) : (
          <Heading title={tPage('title')} description={tPage('subtitle')} />
        )}
        <div className='flex flex-wrap gap-2'>
          <Button
            variant='outline'
            size='sm'
            disabled={activities.length === 0}
            onClick={() => {
              exportActivitiesCsv(activities, `activity-page-${page + 1}.csv`);
              toast.success(tActivity('exportCsvSuccess'));
            }}
          >
            <Download className='size-4' />
            {tActivity('exportCsv')}
          </Button>
          <Button
            variant='outline'
            size='sm'
            onClick={() => refetch()}
            disabled={isFetching}
          >
            {isFetching ? <Loader2 className='size-4 animate-spin' /> : null}
            {tActivity('refresh')}
          </Button>
        </div>
      </div>

      <div className='flex flex-wrap items-end gap-2'>
        <div className='space-y-1'>
          <label className='text-[11px] text-muted-foreground'>
            {tActivity('filterAction')}
          </label>
          <Select
            value={actionFilter}
            onValueChange={(v) => {
              setActionFilter(v);
              setPage(0);
            }}
          >
            <SelectTrigger className='h-8 w-[200px]'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACTION_FILTER_OPTIONS.map((key) => (
                <SelectItem key={key} value={key}>
                  {key === 'all'
                    ? tActivity('filterAll')
                    : getActionLabel(key, tActivity)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className='space-y-1'>
          <label className='text-[11px] text-muted-foreground'>
            {tActivity('filterDevice')}
          </label>
          <Input
            className='h-8 w-[180px]'
            placeholder={tActivity('filterDevicePlaceholder')}
            value={deviceSerial}
            onChange={(e) => {
              setDeviceSerial(e.target.value);
              setPage(0);
            }}
          />
        </div>
        {(actionFilter !== 'all' || deviceSerial.trim()) && (
          <Button
            variant='ghost'
            size='sm'
            className='h-8'
            onClick={resetFilters}
          >
            {tActivity('filterReset')}
          </Button>
        )}
      </div>

      <Card className='gap-0 py-0'>
        <CardContent className='p-0'>
          <ScrollArea
            className={
              embedded
                ? 'h-[min(520px,calc(100dvh-280px))] min-h-[360px]'
                : 'h-[calc(100dvh-320px)] min-h-[420px]'
            }
          >
            {isLoading ? (
              <div className='flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground'>
                <Loader2 size={16} className='animate-spin' />
                {tActivity('loading')}
              </div>
            ) : error ? (
              <div className='py-16 text-center text-sm text-destructive'>
                {tActivity('loadError')}
              </div>
            ) : activities.length === 0 ? (
              <div className='py-16 text-center text-sm text-muted-foreground'>
                {actionFilter !== 'all' || deviceSerial.trim()
                  ? tActivity('emptyFiltered')
                  : tActivity('empty')}
              </div>
            ) : (
              activities.map((item: ActivityLogItem) => (
                <ActivityRow key={item.id} item={item} locale={locale} />
              ))
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      {total > PAGE_SIZE ? (
        <div className='flex items-center justify-between gap-2 text-xs text-muted-foreground'>
          <span>
            {tActivity('pagination', {
              from: page * PAGE_SIZE + 1,
              to: Math.min((page + 1) * PAGE_SIZE, total),
              total
            })}
          </span>
          <div className='flex items-center gap-1'>
            <Button
              variant='outline'
              size='icon'
              className='size-7'
              disabled={page <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <ChevronLeft className='size-4' />
            </Button>
            <span className='min-w-[4rem] text-center tabular-nums'>
              {page + 1} / {pageCount}
            </span>
            <Button
              variant='outline'
              size='icon'
              className='size-7'
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            >
              <ChevronRight className='size-4' />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
