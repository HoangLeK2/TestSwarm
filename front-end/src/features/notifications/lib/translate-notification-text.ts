import type { NotificationItem } from '../services/api';
import {
  resolveDeviceLabel,
  sanitizeNotificationBody
} from './notification-ui';

export type NotificationText = {
  title: string;
  body?: string | null;
};

type TranslateFn = (
  key: string,
  values?: Record<string, string | number>
) => string;

/** Shared inbox/bell copy for legacy + Epic 09 event payloads. */
export function translateNotificationItem(
  item: NotificationItem,
  t: TranslateFn
): NotificationText {
  const payload = item.data ?? {};
  const label = resolveDeviceLabel(item, t('unknownDevice'));

  if (payload.test) {
    return { title: t('testTitle'), body: t('testBody') };
  }
  if (item.event === 'device.disconnect') {
    return {
      title: t('eventTitles.deviceDisconnect', { label }),
      body:
        sanitizeNotificationBody(item.body) ?? t('eventBodies.deviceDisconnect')
    };
  }
  if (item.event === 'device.reconnect') {
    return {
      title: t('eventTitles.deviceReconnect', { label }),
      body:
        sanitizeNotificationBody(item.body) ??
        t('eventBodies.deviceReconnect', { serial: label })
    };
  }
  if (item.event === 'task.failed' && payload.raw_event === 'error') {
    return {
      title: t('eventTitles.deviceError', { label }),
      body: sanitizeNotificationBody(item.body) ?? t('eventBodies.deviceError')
    };
  }
  return {
    title: item.title,
    body: sanitizeNotificationBody(item.body)
  };
}
