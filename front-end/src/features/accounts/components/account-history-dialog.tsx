'use client';

import { useEffect, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import { Activity, AlertCircle, History } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import {
  useAccountActions,
  useAccountActionSummary,
  useAccountEvents
} from '../hooks/use-accounts';
import type { AccountActionOut, AccountOut } from '../services/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const EVENT_VARIANT: Record<
  string,
  'default' | 'secondary' | 'destructive' | 'outline'
> = {
  'account.usage_started': 'default',
  'account.usage_ended': 'secondary',
  'account.picked': 'outline',
  'account.status_changed': 'outline',
  'account.banned': 'destructive',
  'account.session_death': 'destructive',
  'account.cooldown_entered': 'secondary',
  'account.cooldown_cleared': 'default'
};

function eventTypeKey(eventType: string): string {
  return eventType.startsWith('account.')
    ? eventType.slice('account.'.length)
    : eventType;
}

export function AccountHistoryDialog({ account }: { account: AccountOut }) {
  const t = useTranslations('accountsFeature.history');
  const locale = useLocale();
  const dateLocale = locale === 'vi' ? vi : enUS;
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<string | undefined>();
  const [actionCursor, setActionCursor] = useState<string | undefined>();
  const [allItems, setAllItems] = useState<
    import('../services/api').AccountEventOut[]
  >([]);
  const [allActions, setAllActions] = useState<AccountActionOut[]>([]);
  const { data, isLoading, isFetching } = useAccountEvents(account.id, {
    enabled: open,
    cursor
  });
  const actionsQuery = useAccountActions(account.id, {
    enabled: open,
    cursor: actionCursor
  });
  const summaryQuery = useAccountActionSummary(account.id, { enabled: open });

  useEffect(() => {
    if (!open) {
      setCursor(undefined);
      setAllItems([]);
      setActionCursor(undefined);
      setAllActions([]);
      return;
    }
    if (!data?.items) return;
    setAllItems((prev) => (cursor ? [...prev, ...data.items] : data.items));
  }, [data, cursor, open]);

  useEffect(() => {
    if (!open || !actionsQuery.data?.items) return;
    setAllActions((prev) =>
      actionCursor
        ? [...prev, ...actionsQuery.data.items]
        : actionsQuery.data.items
    );
  }, [actionCursor, actionsQuery.data, open]);

  const items = allItems;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='ghost' size='sm' className='h-8 gap-1'>
          <History className='size-3.5' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='flex max-h-[90vh] w-[calc(100vw-1rem)] max-w-2xl flex-col overflow-hidden p-4 sm:p-6'>
        <DialogHeader>
          <DialogTitle>
            {t('title', { username: account.username })}
          </DialogTitle>
        </DialogHeader>
        <Tabs defaultValue='actions' className='flex min-h-0 flex-1 flex-col'>
          <TabsList className='grid w-full grid-cols-2'>
            <TabsTrigger value='actions'>{t('tabs.actions')}</TabsTrigger>
            <TabsTrigger value='events'>{t('tabs.events')}</TabsTrigger>
          </TabsList>
          <TabsContent
            value='actions'
            className='min-h-0 flex-1 space-y-3 overflow-y-auto pr-1'
          >
            {summaryQuery.data && (
              <div className='grid grid-cols-2 gap-2 sm:grid-cols-4'>
                {(['running', 'succeeded', 'failed', 'total'] as const).map(
                  (key) => (
                    <div
                      key={key}
                      className='rounded-lg border bg-muted/30 p-2'
                    >
                      <p className='text-[10px] uppercase text-muted-foreground'>
                        {t(`summary.${key}`)}
                      </p>
                      <p className='text-lg font-semibold'>
                        {summaryQuery.data[key]}
                      </p>
                    </div>
                  )
                )}
              </div>
            )}
            {summaryQuery.data?.current_activity && (
              <div className='flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm'>
                <Activity className='mt-0.5 size-4 shrink-0 text-primary' />
                <div>
                  <p className='font-medium'>{t('currentActivity')}</p>
                  <p className='break-words text-muted-foreground'>
                    {t.has(`actions.${summaryQuery.data.current_activity}`)
                      ? t(`actions.${summaryQuery.data.current_activity}`)
                      : summaryQuery.data.current_activity}
                  </p>
                </div>
              </div>
            )}
            {actionsQuery.isLoading && (
              <p className='text-sm text-muted-foreground'>
                {t('loadingActions')}
              </p>
            )}
            {!actionsQuery.isLoading && allActions.length === 0 && (
              <p className='text-sm text-muted-foreground'>
                {t('emptyActions')}
              </p>
            )}
            {allActions.map((item) => (
              <div
                key={item.id}
                className='rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm'
              >
                <div className='flex flex-wrap items-start justify-between gap-2'>
                  <div className='min-w-0'>
                    <p className='break-words font-medium'>
                      {t.has(`actions.${item.action}`)
                        ? t(`actions.${item.action}`)
                        : item.action}
                    </p>
                    <p className='text-xs text-muted-foreground'>
                      {item.target_label ||
                        [item.target_type, item.target_id]
                          .filter(Boolean)
                          .join(': ') ||
                        t('noTarget')}
                    </p>
                  </div>
                  <Badge
                    variant={
                      item.status === 'failed'
                        ? 'destructive'
                        : item.status === 'succeeded'
                          ? 'default'
                          : 'secondary'
                    }
                  >
                    {t.has(`statuses.${item.status}`)
                      ? t(`statuses.${item.status}`)
                      : item.status}
                  </Badge>
                </div>
                {item.current_activity && (
                  <p className='mt-2 break-words text-xs text-muted-foreground'>
                    <span className='font-medium text-foreground'>
                      {t('activity')}:
                    </span>{' '}
                    {t.has(`actions.${item.current_activity}`)
                      ? t(`actions.${item.current_activity}`)
                      : item.current_activity}
                  </p>
                )}
                {typeof item.details?.outcome === 'string' && (
                  <p className='mt-2 break-words text-xs text-muted-foreground'>
                    <span className='font-medium text-foreground'>
                      {t('outcome')}:
                    </span>{' '}
                    {t.has(`outcomes.${item.details.outcome}`)
                      ? t(`outcomes.${item.details.outcome}`)
                      : item.details.outcome}
                  </p>
                )}
                {typeof item.details?.action_performed === 'boolean' && (
                  <Badge
                    variant='outline'
                    className='mt-2 text-[10px] font-normal'
                  >
                    {item.details.action_performed
                      ? t('actionPerformed')
                      : t('actionNotPerformed')}
                  </Badge>
                )}
                {item.error_message && (
                  <div className='mt-2 flex items-start gap-1.5 rounded bg-destructive/10 p-2 text-xs text-destructive'>
                    <AlertCircle className='mt-0.5 size-3.5 shrink-0' />
                    <span className='break-words'>
                      {item.error_code ? `${item.error_code}: ` : ''}
                      {item.error_message}
                    </span>
                  </div>
                )}
                <p className='mt-2 text-[11px] text-muted-foreground'>
                  {formatDistanceToNow(
                    new Date(item.updated_at || item.created_at),
                    { addSuffix: true, locale: dateLocale }
                  )}
                </p>
              </div>
            ))}
            {actionsQuery.data?.has_more && (
              <Button
                className='w-full'
                variant='outline'
                size='sm'
                disabled={actionsQuery.isFetching}
                onClick={() =>
                  setActionCursor(actionsQuery.data?.next_cursor ?? undefined)
                }
              >
                {t('loadMore')}
              </Button>
            )}
          </TabsContent>
          <TabsContent
            value='events'
            className='min-h-0 flex-1 space-y-3 overflow-y-auto pr-1'
          >
            {isLoading && (
              <p className='text-sm text-muted-foreground'>{t('loading')}</p>
            )}
            {!isLoading && items.length === 0 && (
              <p className='text-sm text-muted-foreground'>{t('empty')}</p>
            )}
            {items.map((ev) => (
              <div
                key={ev.id}
                className='rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm'
              >
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <Badge
                    variant={EVENT_VARIANT[ev.event_type] ?? 'outline'}
                    className='text-[10px] font-normal'
                  >
                    {t.has(`events.${eventTypeKey(ev.event_type)}`)
                      ? t(`events.${eventTypeKey(ev.event_type)}`)
                      : eventTypeKey(ev.event_type)}
                  </Badge>
                  <span className='text-xs text-muted-foreground'>
                    {formatDistanceToNow(new Date(ev.created_at), {
                      addSuffix: true,
                      locale: dateLocale
                    })}
                  </span>
                </div>
                {ev.device_serial && (
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {t('device')}: {ev.device_serial}
                  </p>
                )}
                {ev.entity_type && ev.entity_id && (
                  <p className='text-xs text-muted-foreground'>
                    {ev.entity_type}: {ev.entity_id.slice(0, 8)}…
                  </p>
                )}
                {Object.keys(ev.details ?? {}).length > 0 && (
                  <pre className='mt-1 max-h-24 overflow-auto rounded bg-background/80 p-2 text-[10px] text-muted-foreground'>
                    {JSON.stringify(ev.details, null, 2)}
                  </pre>
                )}
              </div>
            ))}
            {data?.has_more && (
              <Button
                variant='outline'
                size='sm'
                disabled={isFetching}
                onClick={() => setCursor(data.next_cursor ?? undefined)}
              >
                {t('loadMore')}
              </Button>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
