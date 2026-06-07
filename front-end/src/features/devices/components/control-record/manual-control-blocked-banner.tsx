'use client';

import { AlertTriangle } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type Props = {
  canTakeControl: boolean;
  onTakeControl: () => void;
  /** Smaller copy for multi-phone / compact mirror layouts. */
  compact?: boolean;
};

/** Overlay strip at the bottom of the device mirror when manual input is blocked. */
export function ManualControlBlockedBanner({
  canTakeControl,
  onTakeControl,
  compact = false
}: Props) {
  const t = useTranslations('devicesControlRecord.view.takeover');

  return (
    <div
      role='status'
      className={cn(
        'absolute inset-x-0 bottom-0 z-20 border-t border-amber-500/50',
        'bg-amber-50 dark:bg-amber-950',
        compact ? 'px-2.5 py-2' : 'px-3 py-2.5'
      )}
    >
      <div className='flex items-center gap-2.5'>
        <AlertTriangle
          className={cn(
            'shrink-0 text-amber-600 dark:text-amber-400',
            compact ? 'size-3.5' : 'size-4'
          )}
          aria-hidden
        />
        <div className='min-w-0 flex-1'>
          <p
            className={cn(
              'font-semibold leading-tight text-amber-950 dark:text-amber-50',
              compact ? 'text-[11px]' : 'text-xs'
            )}
          >
            {t('blockedTitle')}
          </p>
          <p
            className={cn(
              'leading-snug text-amber-800 dark:text-amber-200/90',
              compact ? 'text-[10px]' : 'text-[11px]'
            )}
          >
            {t('blockedHint')}
          </p>
        </div>
        {canTakeControl ? (
          <Button
            type='button'
            size='sm'
            variant='secondary'
            className={cn(
              'shrink-0 border-amber-600/30 bg-white font-semibold text-amber-950 hover:bg-amber-100',
              'dark:border-amber-400/30 dark:bg-amber-900 dark:text-amber-50 dark:hover:bg-amber-800',
              compact ? 'h-7 px-2.5 text-[10px]' : 'h-8 px-3 text-xs'
            )}
            onClick={onTakeControl}
          >
            {t('takeControlLink')}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
