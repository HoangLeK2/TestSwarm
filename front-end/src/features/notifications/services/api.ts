import { farmApi } from '@/lib/farm-api';

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

export type NotificationChannelType = 'in_app' | 'telegram' | 'webhook';

export type NotificationChannel = {
  id: string;
  name: string;
  type: NotificationChannelType;
  config: Record<string, unknown>;
  events: string[];
  is_enabled: boolean;
  user_id?: string | null;
  created_at: string;
};

export type NotificationItem = {
  id: string;
  channel_id?: string | null;
  event: string;
  title: string;
  body?: string | null;
  data: Record<string, unknown>;
  is_read: boolean;
  sent_at: string;
  user_id?: string | null;
  created_at: string;
};

export type NotificationListResponse = {
  total: number;
  offset: number;
  limit: number;
  notifications: NotificationItem[];
};

export type NotificationChannelInput = {
  name: string;
  type: NotificationChannelType;
  config: Record<string, unknown>;
  events: string[];
  is_enabled: boolean;
};

export const notificationsApi = {
  list: (query?: { unread?: boolean; offset?: number; limit?: number }) =>
    farmApi
      .get<NotificationListResponse>('/notifications', { params: query })
      .then((r) => r.data),

  unreadCount: () =>
    farmApi
      .get<{ count: number }>('/notifications/unread-count')
      .then((r) => r.data.count),

  markRead: (notificationId: string) =>
    farmApi
      .patch<NotificationItem>(`/notifications/${notificationId}/read`, {})
      .then((r) => r.data),

  markAllRead: () =>
    farmApi
      .post<{ count: number }>('/notifications/read-all', {})
      .then((r) => r.data),

  listChannels: () =>
    farmApi
      .get<NotificationChannel[]>('/notification-channels')
      .then((r) => r.data),

  createChannel: (data: NotificationChannelInput) =>
    farmApi
      .post<NotificationChannel>('/notification-channels', data)
      .then((r) => r.data),

  updateChannel: (channelId: string, data: Partial<NotificationChannelInput>) =>
    farmApi
      .patch<NotificationChannel>(`/notification-channels/${channelId}`, data)
      .then((r) => r.data),

  deleteChannel: (channelId: string) =>
    farmApi.delete(`/notification-channels/${channelId}`).then(() => undefined),

  testChannel: (channelId: string) =>
    farmApi
      .post<{
        ok: boolean;
        message: string;
      }>(`/notification-channels/${channelId}/test`, {})
      .then((r) => r.data)
};
