'use client';

import { useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { useRouter } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { NotificationChannelSettings } from './notification-channel-settings';
import { NotificationInbox } from './notification-inbox';

type NotificationsTab = 'inbox' | 'channels';

function parseTab(value: string | null): NotificationsTab {
  return value === 'channels' ? 'channels' : 'inbox';
}

export function NotificationsHub() {
  const t = useTranslations('notificationsFeature');
  const searchParams = useSearchParams();
  const router = useRouter();
  const tab = parseTab(searchParams.get('tab'));

  const setTab = useCallback(
    (next: NotificationsTab) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === 'inbox') params.delete('tab');
      else params.set('tab', next);
      const qs = params.toString();
      router.replace(
        qs ? `/dashboard/notifications?${qs}` : '/dashboard/notifications',
        { scroll: false }
      );
    },
    [router, searchParams]
  );

  return (
    <div className='space-y-4'>
      <div className='space-y-1'>
        <h1 className='text-xl font-bold tracking-tight text-foreground'>
          {t('title')}
        </h1>
        <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(parseTab(v))}>
        <TabsList>
          <TabsTrigger value='inbox'>{t('tabs.inbox')}</TabsTrigger>
          <TabsTrigger value='channels'>{t('tabs.channels')}</TabsTrigger>
        </TabsList>
        <TabsContent value='inbox' className='mt-4'>
          <NotificationInbox />
        </TabsContent>
        <TabsContent value='channels' className='mt-4'>
          <NotificationChannelSettings embedded />
        </TabsContent>
      </Tabs>
    </div>
  );
}
