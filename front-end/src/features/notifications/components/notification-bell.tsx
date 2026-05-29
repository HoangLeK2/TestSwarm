'use client';

import { useCallback, useEffect } from 'react';
import { toast } from 'sonner';
import {
  Bell,
  CheckCheck,
  ExternalLink,
  Loader2,
  Settings
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { subscribeDeviceFarm } from '@/features/devices/services/ws';
import type { WsMessage } from '@/features/devices/types';
import { ROUTES } from '@/config/routes';
import {
  mergeNotification,
  notificationKeys,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadNotificationCount
} from '../hooks/use-notifications';
import type {
  NotificationItem,
  NotificationListResponse
} from '../services/api';

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.max(0, Math.floor(diff / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function NotificationRow({
  item,
  onRead,
  title,
  body
}: {
  item: NotificationItem;
  onRead: (id: string) => void;
  title: string;
  body?: string | null;
}) {
  return (
    <button
      className='flex w-full items-start gap-2 rounded-md px-2 py-2 text-left hover:bg-muted/60'
      onClick={() => {
        if (!item.is_read) onRead(item.id);
      }}
      type='button'
    >
      <span
        className={
          item.is_read
            ? 'mt-1 size-2 rounded-full bg-muted-foreground/30'
            : 'mt-1 size-2 rounded-full bg-primary'
        }
      />
      <span className='min-w-0 flex-1'>
        <span className='block truncate text-xs font-medium'>{title}</span>
        {body ? (
          <span className='mt-0.5 line-clamp-2 block text-[11px] text-muted-foreground'>
            {body}
          </span>
        ) : null}
        <span className='mt-1 flex items-center gap-1.5 text-[10px] text-muted-foreground/70'>
          <span>{item.event}</span>
          <span>{timeAgo(item.created_at)}</span>
        </span>
      </span>
    </button>
  );
}

export function NotificationBell() {
  const t = useTranslations('notificationsFeature');
  const qc = useQueryClient();
  const { data, isLoading } = useNotifications(12);
  const { data: unread = 0 } = useUnreadNotificationCount();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();
  const notifications = data?.notifications ?? [];

  const getNotificationText = useCallback(
    (item: NotificationItem) => {
      const data = item.data ?? {};
      const label =
        [data.device_brand, data.device_model].filter(Boolean).join(' ') ||
        String(data.serial ?? '') ||
        item.title;
      if (data.test) {
        return {
          title: t('testTitle'),
          body: t('testBody')
        };
      }
      if (item.event === 'device.disconnect') {
        return {
          title: t('eventTitles.deviceDisconnect', { label }),
          body: item.body || t('eventBodies.deviceDisconnect')
        };
      }
      if (item.event === 'device.reconnect') {
        return {
          title: t('eventTitles.deviceReconnect', { label }),
          body: t('eventBodies.deviceReconnect', {
            serial: String(data.serial ?? '')
          })
        };
      }
      if (item.event === 'task.failed' && data.raw_event === 'error') {
        return {
          title: t('eventTitles.deviceError', { label }),
          body: item.body || t('eventBodies.deviceError')
        };
      }
      return { title: item.title, body: item.body };
    },
    [t]
  );

  useEffect(() => {
    const unsubscribe = subscribeDeviceFarm((msg: WsMessage) => {
      if (msg.type !== 'notification') return;
      const incoming = msg.data;
      const translated = getNotificationText(incoming);
      qc.setQueryData<NotificationListResponse>(
        [...notificationKeys.list, 12],
        (current) => ({
          total: Math.max(
            current?.total ?? 0,
            (current?.notifications.length ?? 0) + 1
          ),
          offset: current?.offset ?? 0,
          limit: current?.limit ?? 12,
          notifications: mergeNotification(
            current?.notifications ?? [],
            incoming
          )
        })
      );
      qc.setQueryData<number>(
        notificationKeys.unreadCount,
        (current) => (current ?? 0) + 1
      );
      toast(translated.title, {
        description: translated.body ?? undefined,
        duration: 7000
      });
    });
    return unsubscribe;
  }, [getNotificationText, qc]);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant='outline' size='icon' className='relative size-8'>
          <Bell size={15} />
          {unread > 0 ? (
            <Badge
              variant='destructive'
              className='absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px]'
            >
              {unread > 99 ? '99+' : unread}
            </Badge>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align='end'
        className='flex h-[min(480px,calc(100vh-2rem))] w-[360px] flex-col overflow-hidden p-0'
      >
        <div className='flex items-center justify-between border-b px-3 py-2'>
          <div className='flex items-center gap-2 text-sm font-medium'>
            <Bell size={14} />
            {t('title')}
          </div>
          <div className='flex items-center gap-1'>
            <Button
              variant='ghost'
              size='icon'
              className='size-7'
              disabled={unread === 0 || markAllRead.isPending}
              onClick={() => markAllRead.mutate()}
            >
              <CheckCheck size={14} />
            </Button>
            <Button variant='ghost' size='icon' className='size-7' asChild>
              <Link href={ROUTES.NOTIFICATIONS.ROOT}>
                <Settings size={14} />
              </Link>
            </Button>
          </div>
        </div>
        <ScrollArea className='min-h-0 flex-1'>
          <div className='p-1'>
            {isLoading ? (
              <div className='flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground'>
                <Loader2 size={15} className='animate-spin' />
                {t('loading')}
              </div>
            ) : notifications.length === 0 ? (
              <div className='py-10 text-center text-sm text-muted-foreground'>
                {t('empty')}
              </div>
            ) : (
              notifications.map((item) => {
                const translated = getNotificationText(item);
                return (
                  <NotificationRow
                    key={item.id}
                    item={item}
                    title={translated.title}
                    body={translated.body}
                    onRead={(id) => markRead.mutate(id)}
                  />
                );
              })
            )}
          </div>
        </ScrollArea>
        <div className='border-t p-2'>
          <Button
            variant='ghost'
            size='sm'
            className='w-full justify-center gap-1.5'
            asChild
          >
            <Link href={ROUTES.NOTIFICATIONS.ROOT}>
              {t('manageChannels')}
              <ExternalLink size={13} />
            </Link>
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
