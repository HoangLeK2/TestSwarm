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
  'campaign.failed': {
    Icon: AlertTriangle,
    tone: 'danger',
    eventLabelKey: 'campaign_failed'
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

const TONE_CLASSES: Record<
  NotificationTone,
  { icon: string; bg: string }
> = {
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
  return text;
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
