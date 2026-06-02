import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  notificationsApi,
  type NotificationChannelInput,
  type NotificationItem
} from '../services/api';

export type NotificationListQuery = {
  unread?: boolean;
  offset?: number;
  limit?: number;
};

export const notificationKeys = {
  list: (orgId: string | null, query: NotificationListQuery) =>
    ['notifications', orgId, query] as const,
  unreadCount: (orgId: string | null) =>
    ['notifications', 'unread-count', orgId] as const,
  channels: (orgId: string | null) =>
    ['notification-channels', orgId] as const
};

export function useNotifications(query: NotificationListQuery = { limit: 12 }) {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;

  return useQuery({
    queryKey: notificationKeys.list(orgId, query),
    queryFn: () => notificationsApi.list(query),
    enabled: Boolean(orgId),
    staleTime: 5_000
  });
}

export function useUnreadNotificationCount() {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;

  return useQuery({
    queryKey: notificationKeys.unreadCount(orgId),
    queryFn: () => notificationsApi.unreadCount(),
    enabled: Boolean(orgId),
    staleTime: 5_000
  });
}

export function useNotificationChannels() {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;

  return useQuery({
    queryKey: notificationKeys.channels(orgId),
    queryFn: () => notificationsApi.listChannels(),
    enabled: Boolean(orgId),
    staleTime: 5_000
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (notificationId: string) =>
      notificationsApi.markRead(notificationId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] });
    }
  });
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] });
    }
  });
}

export function useCreateNotificationChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: NotificationChannelInput) =>
      notificationsApi.createChannel(data),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['notification-channels'] })
  });
}

export function useUpdateNotificationChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data
    }: {
      id: string;
      data: Partial<NotificationChannelInput>;
    }) => notificationsApi.updateChannel(id, data),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['notification-channels'] })
  });
}

export function useDeleteNotificationChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.deleteChannel(id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['notification-channels'] })
  });
}

export function useTestNotificationChannel() {
  return useMutation({
    mutationFn: (id: string) => notificationsApi.testChannel(id)
  });
}

export function mergeNotification(
  existing: NotificationItem[],
  incoming: NotificationItem
) {
  const next = [
    incoming,
    ...existing.filter((item) => item.id !== incoming.id)
  ];
  return next
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    .slice(0, 20);
}
