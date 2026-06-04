/**
 * Notifications API — thin wrapper over OpenAPI-generated client.
 * Regenerate: `pnpm gen:api:sync`.
 */
import { getDeviceFarmApi } from '@/features/device-farm/services/client';
import type {
  NotificationChannelCreate,
  NotificationChannelOut,
  NotificationChannelPatch,
  NotificationListOut,
  NotificationOut,
  TestNotificationOut
} from '@/features/device-farm/services/generated/DeviceFarmApi';

export const NOTIFICATION_EVENTS = [
  'device.disconnect',
  'device.reconnect',
  'task.failed',
  'campaign.complete',
  'campaign.failed',
  'schedule.triggered',
  'schedule.failed',
  'account.banned',
  'content.milestone'
] as const;

export type NotificationChannelType =
  | 'in_app'
  | 'telegram'
  | 'webhook'
  | 'email'
  | 'slack';

export type NotificationChannel = NotificationChannelOut;
export type NotificationItem = NotificationOut;
export type NotificationListResponse = NotificationListOut;

export type NotificationChannelInput = NotificationChannelCreate;

const df = () => getDeviceFarmApi().api;

export const notificationsApi = {
  list: async (query?: { unread?: boolean; offset?: number; limit?: number }) =>
    (await df().listNotificationsApiNotificationsGet(query)).data,

  unreadCount: async () =>
    (await df().unreadCountApiNotificationsUnreadCountGet()).data.count,

  markRead: async (notificationId: string) =>
    (await df().markReadApiNotificationsNotificationIdReadPatch(notificationId))
      .data,

  markAllRead: async () =>
    (await df().markAllReadApiNotificationsReadAllPost()).data,

  listChannels: async () =>
    (await df().listChannelsApiNotificationChannelsGet()).data,

  createChannel: async (data: NotificationChannelInput) =>
    (await df().createChannelApiNotificationChannelsPost(data)).data,

  updateChannel: async (channelId: string, data: NotificationChannelPatch) =>
    (
      await df().updateChannelApiNotificationChannelsChannelIdPatch(
        channelId,
        data
      )
    ).data,

  deleteChannel: async (channelId: string) => {
    await df().deleteChannelApiNotificationChannelsChannelIdDelete(channelId);
  },

  testChannel: async (channelId: string) =>
    (await df().testChannelApiNotificationChannelsChannelIdTestPost(channelId))
      .data as TestNotificationOut
};
