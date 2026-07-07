'use client';

import { useTranslations } from 'next-intl';

import { cn } from '@/lib/utils';

/** Static phone silhouette — paints immediately as early LCP on control-record. */
export function MirrorPhonePlaceholder({
  className,
  label
}: {
  className?: string;
  label?: string;
}) {
  const t = useTranslations('devicesControlRecord.view');
  const ariaLabel = label ?? t('mirrorPlaceholder');

  return (
    <div
      role='img'
      aria-label={ariaLabel}
      className={cn(
        'mx-auto aspect-[9/19.5] min-h-[480px] w-[min(100%,262px)]',
        'rounded-[2rem] border-[3px] border-zinc-400/30',
        'bg-gradient-to-b from-zinc-300 to-zinc-400',
        'shadow-[inset_0_0_0_1px_rgba(255,255,255,0.35)]',
        'dark:border-zinc-600/40 dark:from-zinc-700 dark:to-zinc-800',
        className
      )}
    />
  );
}
