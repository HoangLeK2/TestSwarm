'use client';

import { useLocale, useTranslations } from 'next-intl';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  MousePointerClick,
  PlayCircle,
  Smartphone,
  Wifi,
  WifiOff,
  XCircle
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Heading } from '@/components/ui/heading';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useActivityLog } from '../hooks/use-activity-log';
import type { ActivityLogItem } from '../services/api';

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

const ACTION_LABEL_KEY: Record<string, string> = {
  'device.connect': 'device_connect',
  'device.disconnect': 'device_disconnect',
  'device.error': 'device_error',
  'task.done': 'task_done',
  'task.failed': 'task_failed',
  'campaign.run': 'campaign_run',
  'campaign.complete': 'campaign_complete',
  'schedule.triggered': 'schedule_triggered'
};

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
    action === 'device.disconnect' ||
    action === 'device.error'
  ) {
    return 'text-destructive';
  }
  if (
    action.endsWith('.done') ||
    action.endsWith('.complete') ||
    action === 'device.connect'
  ) {
    return 'text-emerald-500';
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
  if (action.startsWith('user.')) {
    return t('actionLabels.user_action');
  }
  const labelKey = ACTION_LABEL_KEY[action];
  if (labelKey) {
    return t(`actionLabels.${labelKey}` as 'actionLabels.device_connect');
  }
  return action;
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
    return t(`operationLabels.${labelKey}` as 'operationLabels.device_interrupt');
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
    default:
      return getActionLabel(item.action, t);
  }
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

function getActivityDescription(
  item: ActivityLogItem,
  t: ReturnType<typeof useTranslations>
) {
  const details = item.details ?? {};
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
  const Icon =
    item.action.startsWith('user.')
      ? MousePointerClick
      : ACTION_ICON[item.action as keyof typeof ACTION_ICON] ?? Smartphone;
  const description = getActivityDescription(item, t);

  return (
    <div className='grid grid-cols-[28px_1fr_auto] gap-3 border-b px-4 py-3 last:border-0'>
      <div className='flex size-7 items-center justify-center rounded-md bg-muted'>
        <Icon size={15} className={actionTone(item.action)} />
      </div>
      <div className='min-w-0'>
        <div className='flex flex-wrap items-center gap-2'>
          <p className='break-words text-sm font-medium'>
            {getActivityTitle(item, t)}
          </p>
          <Badge variant='outline' className='shrink-0 text-[10px]'>
            {getActionLabel(item.action, t)}
          </Badge>
        </div>
        {description ? (
          <p className='mt-1 break-words text-[11px] text-muted-foreground'>
            {description}
          </p>
        ) : null}
      </div>
      <div className='whitespace-nowrap text-xs text-muted-foreground'>
        {formatDate(item.created_at, locale)}
      </div>
    </div>
  );
}

export function ActivityFeed() {
  const tPage = useTranslations('analyticsFeature.dashboard');
  const t = useTranslations('analyticsFeature.activity');
  const locale = useLocale();
  const { data, isLoading, error, refetch, isFetching } = useActivityLog(50);
  const activities = data?.activities ?? [];

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <Heading title={tPage('title')} description={tPage('subtitle')} />
        <Button
          variant='outline'
          size='sm'
          onClick={() => refetch()}
          disabled={isFetching}
        >
          {isFetching ? <Loader2 className='size-4 animate-spin' /> : null}
          {t('refresh')}
        </Button>
      </div>
      <Card className='gap-0 py-0'>
        <CardContent className='p-0'>
          <ScrollArea className='h-[calc(100dvh-220px)] min-h-[420px]'>
            {isLoading ? (
              <div className='flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground'>
                <Loader2 size={16} className='animate-spin' />
                {t('loading')}
              </div>
            ) : error ? (
              <div className='py-16 text-center text-sm text-destructive'>
                {t('loadError')}
              </div>
            ) : activities.length === 0 ? (
              <div className='py-16 text-center text-sm text-muted-foreground'>
                {t('empty')}
              </div>
            ) : (
              activities.map((item) => (
                <ActivityRow key={item.id} item={item} locale={locale} />
              ))
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
