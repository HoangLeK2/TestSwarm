'use client';

import type { LucideIcon } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export type AnalyticsKpiTone = 'neutral' | 'success' | 'danger' | 'accent';

const toneStyles: Record<
  AnalyticsKpiTone,
  { border: string; icon: string; iconBg: string }
> = {
  neutral: {
    border: 'border-border',
    icon: 'text-muted-foreground',
    iconBg: 'bg-muted/60'
  },
  success: {
    border: 'border-emerald-500/25',
    icon: 'text-emerald-600 dark:text-emerald-400',
    iconBg: 'bg-emerald-500/10'
  },
  danger: {
    border: 'border-destructive/25',
    icon: 'text-destructive',
    iconBg: 'bg-destructive/10'
  },
  accent: {
    border: 'border-primary/25',
    icon: 'text-primary',
    iconBg: 'bg-primary/10'
  }
};

type Props = {
  label: string;
  value: string | number | null | undefined;
  loading?: boolean;
  icon: LucideIcon;
  tone?: AnalyticsKpiTone;
};

export function AnalyticsKpiCard({
  label,
  value,
  loading,
  icon: Icon,
  tone = 'neutral'
}: Props) {
  const styles = toneStyles[tone];
  const display =
    value == null || value === ''
      ? '—'
      : typeof value === 'number'
        ? value.toLocaleString()
        : value;

  return (
    <div
      className={cn(
        'flex items-start justify-between gap-3 rounded-xl border bg-card p-4 shadow-sm',
        styles.border
      )}
    >
      <div className='min-w-0 flex-1'>
        <p className='text-xs font-medium text-muted-foreground'>{label}</p>
        {loading ? (
          <Skeleton className='mt-2 h-8 w-24' />
        ) : (
          <p className='mt-1 truncate text-2xl font-semibold tabular-nums tracking-tight text-foreground'>
            {display}
          </p>
        )}
      </div>
      <div
        className={cn(
          'flex size-10 shrink-0 items-center justify-center rounded-lg',
          styles.iconBg
        )}
      >
        <Icon className={cn('size-5', styles.icon)} strokeWidth={1.75} />
      </div>
    </div>
  );
}
