'use client';

import { AlertTriangle } from 'lucide-react';
import { useTranslations } from 'next-intl';

type Props = {
  canTakeControl: boolean;
  onTakeControl: () => void;
};

/** Shown below the device mirror when campaign/scenario blocks manual input. */
export function ManualControlBlockedBanner({
  canTakeControl,
  onTakeControl
}: Props) {
  const t = useTranslations('devicesControlRecord.view.takeover');

  return (
    <div
      role='status'
      className='flex w-full shrink-0 items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-50/90 px-2.5 py-1.5 text-amber-950 shadow-sm dark:border-amber-500/25 dark:bg-amber-950/50 dark:text-amber-100'
    >
      <AlertTriangle
        className='size-3.5 shrink-0 text-amber-600 dark:text-amber-400'
        aria-hidden
      />
      <p className='min-w-0 flex-1 text-[11px] leading-snug text-amber-950 dark:text-amber-100'>
        <span className='font-medium'>{t('blockedTitle')}</span>
        <span className='text-amber-800/75 dark:text-amber-200/75'>
          {' '}
          {t('blockedHint')}
        </span>
      </p>
      {canTakeControl ? (
        <button
          type='button'
          onClick={onTakeControl}
          className='shrink-0 rounded-md px-2 py-1 text-[10px] font-semibold text-amber-900 ring-1 ring-amber-500/30 transition-colors hover:bg-amber-200/70 dark:text-amber-50 dark:hover:bg-amber-900/50'
        >
          {t('takeControlLink')}
        </button>
      ) : null}
    </div>
  );
}
