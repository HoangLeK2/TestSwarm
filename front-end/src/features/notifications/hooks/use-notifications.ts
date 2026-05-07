import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  notificationsApi,
  type NotificationChannelInput,
  type NotificationItem
} from '../services/api';

export const notificationKeys = {
  list: ['notifications'] as const,
  unreadCount: ['notifications', 'unread-count'] as const,
  channels: ['notification-channels'] as const
};

export function useNotifications(limit = 12) {
  return useQuery({
    queryKey: [...notificationKeys.list, limit],
    queryFn: () => notificationsApi.list({ limit }),
    staleTime: 5_000
  });
}

export function useUnreadNotificationCount() {
  return useQuery({
    queryKey: notificationKeys.unreadCount,
    queryFn: () => notificationsApi.unreadCount(),
    staleTime: 5_000
  });
}

export function useNotificationChannels() {
  return useQuery({
    queryKey: notificationKeys.channels,
    queryFn: () => notificationsApi.listChannels(),
    staleTime: 5_000
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (notificationId: string) => notificationsApi.markRead(notificationId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: notificationKeys.list });
      qc.invalidateQueries({ queryKey: notificationKeys.unreadCount });
    }
  });
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: notificationKeys.list });
      qc.invalidateQueries({ queryKey: notificationKeys.unreadCount });
    }
  });
}

export function useCreateNotificationChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: NotificationChannelInput) => notificationsApi.createChannel(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: notificationKeys.channels })
  });
}

export function useUpdateNotificationChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<NotificationChannelInput> }) =>
      notificationsApi.updateChannel(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: notificationKeys.channels })
  });
}

export function useDeleteNotificationChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.deleteChannel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: notificationKeys.channels })
  });
}

export function useTestNotificationChannel() {
  return useMutation({
    mutationFn: (id: string) => notificationsApi.testChannel(id)
  });
}

export function mergeNotification(existing: NotificationItem[], incoming: NotificationItem) {
  const next = [incoming, ...existing.filter((item) => item.id !== incoming.id)];
  return next
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 20);
}
