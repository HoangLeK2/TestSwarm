'use client';

import { useCallback, useMemo, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import Link from 'next/link';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  Loader2,
  LogIn,
  MousePointerClick,
  FileText,
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
  const Icon = getActivityIcon(item.action);
  const title = getActivityTitle(item, t);
  const categoryBadge = getActivityCategoryBadge(item, title, t);
  const description = getActivityDescription(item, t);
  const deepLink = activityLogDeepLink(item);
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
