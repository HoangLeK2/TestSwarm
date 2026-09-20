'use client';

import { CalendarClock } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import type { ReactNode } from 'react';
import type { AccountOut } from '../services/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';

type Props = {
  account: AccountOut;
  trigger?: ReactNode;
};

function formatDateTime(value: string | null | undefined, locale: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(date);
}

export function AccountVerificationSetupDialog({ account, trigger }: Props) {
  const t = useTranslations('accountsFeature.verificationSetup');
  const locale = useLocale();
  const hold = account.verification_hold;
  const remindAt = hold?.remind_at ?? account.verification_hold_until;
  const channels = [
    hold?.notify_web ? t('channelWeb') : null,
    hold?.notify_telegram ? t('channelTelegram') : null
  ].filter(Boolean);

  return (
    <Dialog>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant='outline' size='sm' className='h-8 gap-1'>
            <CalendarClock className='size-3.5' />
            {t('trigger')}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription>
            {t('description', {
              username: account.display_name || account.username || account.id
            })}
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-3 rounded-md border p-3 text-sm'>
          <div className='space-y-1'>
            <p className='text-xs font-medium text-muted-foreground'>
              {t('reminderTime')}
            </p>
            <p className='font-medium'>{formatDateTime(remindAt, locale)}</p>
          </div>
          <div className='space-y-1'>
            <p className='text-xs font-medium text-muted-foreground'>
              {t('preset')}
            </p>
            <p>{hold ? t(`presetValues.${hold.preset}`) : t('notSet')}</p>
          </div>
          <div className='space-y-1'>
            <p className='text-xs font-medium text-muted-foreground'>
              {t('channels')}
            </p>
            <p>{channels.length ? channels.join(', ') : t('noChannels')}</p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
