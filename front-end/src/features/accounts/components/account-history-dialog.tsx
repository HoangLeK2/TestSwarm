'use client';

import { useEffect, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { History } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useAccountEvents } from '../hooks/use-accounts';
import type { AccountOut } from '../services/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';

const EVENT_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  'account.usage_started': 'default',
  'account.usage_ended': 'secondary',
  'account.picked': 'outline',
  'account.status_changed': 'outline',
  'account.banned': 'destructive',
  'account.session_death': 'destructive',
  'account.cooldown_entered': 'secondary',
  'account.cooldown_cleared': 'default'
};

export function AccountHistoryDialog({ account }: { account: AccountOut }) {
  const t = useTranslations('accountsFeature.history');
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<string | undefined>();
  const [allItems, setAllItems] = useState<
    import('../services/api').AccountEventOut[]
  >([]);
  const { data, isLoading, isFetching } = useAccountEvents(account.id, {
    enabled: open,
    cursor
  });

  useEffect(() => {
    if (!open) {
      setCursor(undefined);
      setAllItems([]);
      return;
    }
    if (!data?.items) return;
    setAllItems((prev) =>
      cursor ? [...prev, ...data.items] : data.items
    );
  }, [data, cursor, open]);

  const items = allItems;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='ghost' size='sm' className='h-8 gap-1'>
          <History className='size-3.5' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='max-h-[85vh] max-w-lg overflow-hidden flex flex-col'>
        <DialogHeader>
          <DialogTitle>{t('title', { username: account.username })}</DialogTitle>
        </DialogHeader>
        <div className='flex-1 overflow-y-auto space-y-3 pr-1'>
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
                  {ev.event_type.replace('account.', '')}
                </Badge>
                <span className='text-xs text-muted-foreground'>
                  {formatDistanceToNow(new Date(ev.created_at), {
                    addSuffix: true,
                    locale: vi
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
        </div>
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
      </DialogContent>
    </Dialog>
  );
}
