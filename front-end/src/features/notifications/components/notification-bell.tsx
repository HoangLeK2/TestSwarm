'use client';

import { useCallback, useEffect } from 'react';
import { toast } from 'sonner';
import {
  Bell,
  BellOff,
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { subscribeDeviceFarm } from '@/features/devices/services/ws';
import type { WsMessage } from '@/features/devices/types';
import { ROUTES } from '@/config/routes';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  getNotificationToneClasses,
  getNotificationVisual,
  groupNotificationsByDay,
  resolveDeviceLabel,
  sanitizeNotificationBody,
  timeAgo
} from '../lib/notification-ui';
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

function NotificationRow({
  item,
  title,
  body,
  onRead
}: {
  item: NotificationItem;
  title: string;
  body?: string | null;
  onRead: (id: string) => void;
}) {
  const visual = getNotificationVisual(item.event);
  const toneClasses = getNotificationToneClasses(visual.tone);
  const { Icon } = visual;
  const detail = sanitizeNotificationBody(body);

  return (
    <button
      className={cn(
        'group flex w-full items-start gap-3 rounded-md px-2 py-2.5 text-left transition-colors hover:bg-muted/50',
        !item.is_read && 'bg-muted/25 hover:bg-muted/45'
      )}
      onClick={() => {
        if (!item.is_read) onRead(item.id);
      }}
      type='button'
    >
      <span className='relative mt-0.5 shrink-0'>
        <span
          className={cn(
            'flex size-9 items-center justify-center rounded-full',
            toneClasses.bg
          )}
        >
          <Icon className={cn('size-4', toneClasses.icon)} aria-hidden />
        </span>
        {!item.is_read ? (
          <span className='absolute -right-0.5 -top-0.5 size-2 rounded-full bg-primary ring-2 ring-background' />
        ) : null}
      </span>
      <span className='min-w-0 flex-1 pt-0.5'>
        <span className='flex items-start justify-between gap-3'>
          <span
            className={cn(
              'line-clamp-2 text-[13px] leading-snug',
              item.is_read
                ? 'font-normal text-foreground/80'
                : 'font-medium text-foreground'
            )}
          >
            {title}
          </span>
          <span className='shrink-0 pt-0.5 text-[11px] tabular-nums text-muted-foreground/60'>
            {timeAgo(item.created_at)}
          </span>
        </span>
        {detail ? (
          <span className='mt-0.5 line-clamp-2 block text-xs leading-relaxed text-muted-foreground'>
            {detail}
          </span>
        ) : null}
      </span>
    </button>
  );
}

function NotificationGroup({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className='px-2 pb-1 text-[11px] font-medium text-muted-foreground/70'>
        {label}
      </p>
      <div className='flex flex-col'>{children}</div>
    </div>
  );
}

export function NotificationBell() {
  const t = useTranslations('notificationsFeature');
  const qc = useQueryClient();
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  const { data, isLoading } = useNotifications(12);
  const { data: unread = 0 } = useUnreadNotificationCount();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();
  const notifications = data?.notifications ?? [];
  const { today, earlier } = groupNotificationsByDay(notifications);

  const getNotificationText = useCallback(
    (item: NotificationItem) => {
      const data = item.data ?? {};
      const label = resolveDeviceLabel(item, t('unknownDevice'));
      if (data.test) {
        return {
          title: t('testTitle'),
          body: t('testBody')
        };
      }
      if (item.event === 'device.disconnect') {
        return {
          title: t('eventTitles.deviceDisconnect', { label }),
          body:
            sanitizeNotificationBody(item.body) ??
            t('eventBodies.deviceDisconnect')
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
      if (item.event === 'task.failed' && data.raw_event === 'error') {
        return {
          title: t('eventTitles.deviceError', { label }),
          body:
            sanitizeNotificationBody(item.body) ??
            t('eventBodies.deviceError')
        };
      }
      return {
        title: item.title,
        body: sanitizeNotificationBody(item.body)
      };
    },
    [t]
  );

  useEffect(() => {
    if (!orgId) return;
    const unsubscribe = subscribeDeviceFarm((msg: WsMessage) => {
      if (msg.type !== 'notification') return;
      const incoming = msg.data;
      const translated = getNotificationText(incoming);
      qc.setQueryData<NotificationListResponse>(
        notificationKeys.list(orgId, 12),
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
        notificationKeys.unreadCount(orgId),
        (current) => (current ?? 0) + 1
      );
      toast(translated.title, {
        description: translated.body ?? undefined,
        duration: 7000
      });
    });
    return unsubscribe;
  }, [getNotificationText, orgId, qc]);

  const renderItems = (items: NotificationItem[]) =>
    items.map((item) => {
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
    });

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
        className='flex h-[min(520px,calc(100vh-2rem))] w-[380px] flex-col overflow-hidden p-0'
      >
        <div className='flex items-center justify-between border-b px-3.5 py-2.5'>
          <div className='flex min-w-0 items-center gap-2'>
            <Bell size={15} className='shrink-0 text-muted-foreground' />
            <span className='text-sm font-semibold'>{t('title')}</span>
            {unread > 0 ? (
              <Badge
                variant='secondary'
                className='h-5 rounded-md px-1.5 text-[10px] font-medium tabular-nums'
              >
                {t('unreadBadge', { count: unread > 99 ? '99+' : unread })}
              </Badge>
            ) : null}
          </div>
          <div className='flex items-center gap-0.5'>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant='ghost'
                  size='icon'
                  className='size-7'
                  disabled={unread === 0 || markAllRead.isPending}
                  onClick={() => markAllRead.mutate()}
                >
                  <CheckCheck size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side='bottom'>{t('markAllRead')}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant='ghost' size='icon' className='size-7' asChild>
                  <Link href={ROUTES.NOTIFICATIONS.ROOT}>
                    <Settings size={14} />
                  </Link>
                </Button>
              </TooltipTrigger>
              <TooltipContent side='bottom'>{t('manageChannels')}</TooltipContent>
            </Tooltip>
          </div>
        </div>
        <ScrollArea className='min-h-0 flex-1'>
          <div className='space-y-3 px-1 py-2'>
            {isLoading ? (
              <div className='flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground'>
                <Loader2 size={15} className='animate-spin' />
                {t('loading')}
              </div>
            ) : notifications.length === 0 ? (
              <div className='flex flex-col items-center gap-2 py-12 text-center'>
                <span className='mb-2 flex size-10 items-center justify-center rounded-full bg-muted'>
                  <BellOff size={18} className='text-muted-foreground' />
                </span>
                <p className='text-sm font-medium'>{t('empty')}</p>
                <p className='mt-1 max-w-[240px] text-xs text-muted-foreground'>
                  {t('emptyHint')}
                </p>
              </div>
            ) : (
              <>
                {today.length > 0 ? (
                  <NotificationGroup label={t('timeGroupToday')}>
                    {renderItems(today)}
                  </NotificationGroup>
                ) : null}
                {earlier.length > 0 ? (
                  <NotificationGroup label={t('timeGroupEarlier')}>
                    {renderItems(earlier)}
                  </NotificationGroup>
                ) : null}
              </>
            )}
          </div>
        </ScrollArea>
        <div className='border-t p-2'>
          <Button
            variant='ghost'
            size='sm'
            className='w-full justify-center gap-1.5 text-muted-foreground hover:text-foreground'
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
