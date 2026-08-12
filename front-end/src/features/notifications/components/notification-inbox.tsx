'use client';

import { useState } from 'react';
import { BellOff, CheckCheck, ExternalLink, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import {
  collapseRepeatedDeviceDisconnects,
  getNotificationToneClasses,
  getNotificationVisual,
  groupNotificationsByDay,
  notificationMemberIds,
  resolveNotificationHref,
  sanitizeNotificationBody,
  timeAgo
} from '../lib/notification-ui';
import { translateNotificationItem } from '../lib/translate-notification-text';
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadNotificationCount
} from '../hooks/use-notifications';
import type { NotificationItem } from '../services/api';

const PAGE_SIZE = 30;

function InboxRow({
  item,
  title,
  body,
  onRead
}: {
  item: NotificationItem;
  title: string;
  body?: string | null;
  onRead: (ids: string[]) => void;
}) {
  const t = useTranslations('notificationsFeature');
  const visual = getNotificationVisual(item.event);
  const toneClasses = getNotificationToneClasses(visual.tone);
  const { Icon } = visual;
  const detail = sanitizeNotificationBody(body);
  const href = resolveNotificationHref(item);

  return (
    <div
      className={cn(
        'flex items-start gap-3 border-b px-4 py-3 last:border-0',
        !item.is_read && 'bg-muted/20'
      )}
    >
      <span
        className={cn(
          'mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full',
          toneClasses.bg
        )}
      >
        <Icon className={cn('size-4', toneClasses.icon)} aria-hidden />
      </span>
      <button
        type='button'
        className='min-w-0 flex-1 text-left'
        onClick={() => {
          if (!item.is_read) onRead(notificationMemberIds(item));
        }}
      >
        <div className='flex items-start justify-between gap-2'>
          <p
            className={cn(
              'text-sm leading-snug',
              item.is_read ? 'font-normal text-foreground/85' : 'font-medium'
            )}
          >
            {title}
          </p>
          <span className='shrink-0 text-[11px] tabular-nums text-muted-foreground'>
            {timeAgo(item.created_at)}
          </span>
        </div>
        {detail ? (
          <p className='mt-1 text-xs text-muted-foreground'>{detail}</p>
        ) : null}
      </button>
      {href ? (
        <Button variant='ghost' size='icon' className='size-8 shrink-0' asChild>
          <Link href={href}>
            <ExternalLink className='size-3.5' />
            <span className='sr-only'>{t('openRelated')}</span>
          </Link>
        </Button>
      ) : null}
    </div>
  );
}

export function NotificationInbox() {
  const t = useTranslations('notificationsFeature');
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [offset, setOffset] = useState(0);
  const query = {
    limit: PAGE_SIZE,
    offset,
    unread: filter === 'unread' ? true : undefined
  };
  const { data, isLoading } = useNotifications(query);
  const { data: unread = 0 } = useUnreadNotificationCount();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();
  const notifications = data?.notifications ?? [];
  const visibleNotifications = collapseRepeatedDeviceDisconnects(notifications);
  const total = data?.total ?? 0;
  const hasMore = offset + notifications.length < total;

  const { today, earlier } = groupNotificationsByDay(visibleNotifications);

  const renderGroup = (label: string, items: NotificationItem[]) =>
    items.length > 0 ? (
      <div key={label}>
        <p className='px-4 py-2 text-[11px] font-medium text-muted-foreground'>
          {label}
        </p>
        {items.map((item) => {
          const translated = translateNotificationItem(item, t);
          return (
            <InboxRow
              key={item.id}
              item={item}
              title={translated.title}
              body={translated.body}
              onRead={(ids) => ids.forEach((id) => markRead.mutate(id))}
            />
          );
        })}
      </div>
    ) : null;

  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div className='flex items-center gap-2'>
          <Select
            value={filter}
            onValueChange={(v) => {
              setFilter(v as 'all' | 'unread');
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-[140px]'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>{t('inbox.filterAll')}</SelectItem>
              <SelectItem value='unread'>{t('inbox.filterUnread')}</SelectItem>
            </SelectContent>
          </Select>
          {unread > 0 ? (
            <Badge variant='secondary' className='tabular-nums'>
              {t('unreadBadge', { count: unread })}
            </Badge>
          ) : null}
        </div>
        <Button
          variant='outline'
          size='sm'
          disabled={unread === 0 || markAllRead.isPending}
          onClick={() => markAllRead.mutate()}
        >
          <CheckCheck className='mr-2 size-4' />
          {t('markAllRead')}
        </Button>
      </div>

      <Card className='gap-0 py-0'>
        <CardContent className='p-0'>
          <ScrollArea className='h-[min(560px,calc(100dvh-280px))]'>
            {isLoading && visibleNotifications.length === 0 ? (
              <div className='flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground'>
                <Loader2 className='size-4 animate-spin' />
                {t('loading')}
              </div>
            ) : visibleNotifications.length === 0 ? (
              <div className='flex flex-col items-center gap-2 py-16 text-center'>
                <BellOff className='size-8 text-muted-foreground' />
                <p className='text-sm font-medium'>{t('empty')}</p>
                <p className='max-w-sm text-xs text-muted-foreground'>
                  {t('emptyHint')}
                </p>
              </div>
            ) : (
              <>
                {renderGroup(t('timeGroupToday'), today)}
                {renderGroup(t('timeGroupEarlier'), earlier)}
              </>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      {total > PAGE_SIZE ? (
        <div className='flex justify-center gap-2'>
          <Button
            variant='outline'
            size='sm'
            disabled={offset === 0}
            onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}
          >
            {t('inbox.prev')}
          </Button>
          <Button
            variant='outline'
            size='sm'
            disabled={!hasMore}
            onClick={() => setOffset((v) => v + PAGE_SIZE)}
          >
            {t('inbox.next')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
