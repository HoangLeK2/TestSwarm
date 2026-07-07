import {
  AlertTriangle,
  Ban,
  CalendarClock,
  CheckCircle2,
  Flag,
  Megaphone,
  Wifi,
  WifiOff,
  type LucideIcon
} from 'lucide-react';
import { ROUTES } from '@/config/routes';
import type { NotificationItem } from '../services/api';

export type NotificationTone = 'danger' | 'success' | 'warning' | 'info';

export type NotificationVisual = {
  Icon: LucideIcon;
  tone: NotificationTone;
  eventLabelKey: string;
};

const EVENT_VISUALS: Record<string, NotificationVisual> = {
  'device.disconnect': {
    Icon: WifiOff,
    tone: 'danger',
    eventLabelKey: 'device_disconnect'
  },
  'device.reconnect': {
    Icon: Wifi,
    tone: 'success',
    eventLabelKey: 'device_reconnect'
  },
  'task.failed': {
    Icon: AlertTriangle,
    tone: 'warning',
    eventLabelKey: 'task_failed'
  },
  'campaign.complete': {
    Icon: CheckCircle2,
    tone: 'success',
    eventLabelKey: 'campaign_complete'
  },
  'campaign.dispatched': {
    Icon: Megaphone,
    tone: 'info',
    eventLabelKey: 'campaign_dispatched'
  },
  'campaign.completed': {
    Icon: CheckCircle2,
    tone: 'success',
    eventLabelKey: 'campaign_completed'
  },
  'campaign.failed': {
    Icon: AlertTriangle,
    tone: 'danger',
    eventLabelKey: 'campaign_failed'
  },
  'campaign.step_warning': {
    Icon: AlertTriangle,
    tone: 'warning',
    eventLabelKey: 'campaign_step_warning'
  },
  'schedule.triggered': {
    Icon: CalendarClock,
    tone: 'info',
    eventLabelKey: 'schedule_triggered'
  },
  'schedule.failed': {
    Icon: CalendarClock,
    tone: 'danger',
    eventLabelKey: 'schedule_failed'
  },
  'account.banned': {
    Icon: Ban,
    tone: 'danger',
    eventLabelKey: 'account_banned'
  },
  'content.milestone': {
    Icon: Flag,
    tone: 'info',
    eventLabelKey: 'content_milestone'
  }
};

const TONE_CLASSES: Record<NotificationTone, { icon: string; bg: string }> = {
  danger: {
    icon: 'text-destructive',
    bg: 'bg-destructive/10'
  },
  success: {
    icon: 'text-emerald-600 dark:text-emerald-400',
    bg: 'bg-emerald-500/10'
  },
  warning: {
    icon: 'text-amber-600 dark:text-amber-400',
    bg: 'bg-amber-500/10'
  },
  info: {
    icon: 'text-primary',
    bg: 'bg-primary/10'
  }
};

const LOCAL_FRONTEND_ORIGIN_RE =
  /https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?=\/)/gi;

export function getNotificationVisual(event: string): NotificationVisual {
  if (event === 'task.failed') {
    return EVENT_VISUALS['task.failed'];
  }
  return (
    EVENT_VISUALS[event] ?? {
      Icon: Megaphone,
      tone: 'info',
      eventLabelKey: event.replace(/\./g, '_')
    }
  );
}

export function getNotificationToneClasses(tone: NotificationTone) {
  return TONE_CLASSES[tone];
}

export function sanitizeNotificationBody(body?: string | null) {
  const text = body?.trim();
  if (!text) return null;
  if (text.toLowerCase() === 'unknown') return null;
  return text.replace(LOCAL_FRONTEND_ORIGIN_RE, '');
}

export function resolveDeviceLabel(
  item: NotificationItem,
  unknownLabel: string
): string {
  const data = item.data ?? {};
  const brandModel = [data.device_brand, data.device_model]
    .filter(Boolean)
    .join(' ')
    .trim();
  if (brandModel) return brandModel;

  const name = String(data.device_name ?? '').trim();
  if (name && name.toLowerCase() !== 'unknown') return name;

  const serial = String(data.serial ?? '').trim();
  if (serial && serial.toLowerCase() !== 'unknown') return serial;

  const title = item.title.trim();
  if (title && title.toLowerCase() !== 'unknown') return title;

  return unknownLabel;
}

export function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.max(0, Math.floor(diff / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export function isToday(iso: string) {
  const date = new Date(iso);
  const now = new Date();
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  );
}

function pathFromDeepLink(raw: string): string | null {
  try {
    const pathname = raw.startsWith('http')
      ? new URL(raw).pathname
      : raw.startsWith('/')
        ? raw
        : `/${raw}`;
    if (pathname.startsWith('/dashboard')) return pathname;

    const [resource, id, ...rest] = pathname.split('/').filter(Boolean);
    if (resource === 'campaigns' && id) {
      return ROUTES.CAMPAIGNS.DETAIL(id);
    }
    if (resource === 'content' && id) {
      return ROUTES.CONTENT.DETAIL(id);
    }
    if (resource === 'schedules') {
      return ROUTES.SCHEDULES.ROOT;
    }
    if (resource === 'accounts' && id) {
      return ROUTES.ACCOUNTS.ROOT;
    }
    if (resource === 'devices' && id) {
      return ROUTES.DEVICES.CONTROL_RECORD_WITH_SERIAL(id);
    }
    if (resource === 'executions' && id) {
      const campaignId = String(rest[0] ?? '').trim();
      if (campaignId) return ROUTES.CAMPAIGNS.DETAIL(campaignId);
    }
  } catch {
    return null;
  }
  return null;
}

export function resolveNotificationHref(item: NotificationItem): string | null {
  const data = item.data ?? {};
  const deepLink = String(data.deep_link ?? '').trim();
  if (deepLink) {
    const mapped = pathFromDeepLink(deepLink);
    if (mapped) return mapped;
  }

  const campaignId = String(data.campaign_id ?? '').trim();
  if (campaignId) return ROUTES.CAMPAIGNS.DETAIL(campaignId);

  const scheduleId = String(data.schedule_id ?? '').trim();
  if (scheduleId) return ROUTES.SCHEDULES.ROOT;

  const contentId = String(data.content_id ?? '').trim();
  if (contentId) return ROUTES.CONTENT.DETAIL(contentId);

  const serial = String(data.serial ?? data.device_serial ?? '').trim();
  if (serial && item.event.startsWith('device.')) {
    return ROUTES.DEVICES.MANAGE;
  }

  if (item.event.startsWith('campaign.')) return ROUTES.CAMPAIGNS.ROOT;
  if (item.event.startsWith('schedule.')) return ROUTES.SCHEDULES.ROOT;
  if (item.event.startsWith('account.')) return ROUTES.ACCOUNTS.ROOT;

  return null;
}

export function groupNotificationsByDay<T extends { created_at: string }>(
  items: T[]
) {
  const today: T[] = [];
  const earlier: T[] = [];
  for (const item of items) {
    if (isToday(item.created_at)) today.push(item);
    else earlier.push(item);
  }
  return { today, earlier };
}
