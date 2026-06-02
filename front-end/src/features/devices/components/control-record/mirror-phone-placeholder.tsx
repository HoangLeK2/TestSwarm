import { cn } from '@/lib/utils';

/** Static phone silhouette — paints immediately as early LCP on control-record. */
export function MirrorPhonePlaceholder({
  className,
  label = 'Mirror thiết bị'
}: {
  className?: string;
  label?: string;
}) {
  return (
    <div
      role='img'
      aria-label={label}
      className={cn(
        'mx-auto aspect-[9/19.5] w-[min(100%,262px)] min-h-[480px]',
        'rounded-[2rem] border-[3px] border-zinc-400/30',
        'bg-gradient-to-b from-zinc-300 to-zinc-400',
        'shadow-[inset_0_0_0_1px_rgba(255,255,255,0.35)]',
        'dark:border-zinc-600/40 dark:from-zinc-700 dark:to-zinc-800',
        className
      )}
    />
  );
}
