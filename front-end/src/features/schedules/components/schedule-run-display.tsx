'use client';

import { Ban, CheckCircle2, CircleDashed, Clock3, XCircle } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type ScheduleRunState =
  | 'pending'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'unknown';

export function scheduleRunState(status: string): ScheduleRunState {
  const normalized = status.toLowerCase();
  if (normalized === 'pending') return 'pending';
  if (normalized === 'queued') return 'queued';
  if (normalized === 'running') return 'running';
  if (['success', 'succeeded', 'completed', 'done'].includes(normalized)) {
    return 'completed';
  }
  if (['failed', 'error'].includes(normalized)) return 'failed';
  if (['cancelled', 'canceled'].includes(normalized)) return 'cancelled';
  return 'unknown';
}

export function ScheduleRunStatusBadge({
  status,
  className
}: {
  status: string;
  className?: string;
}) {
  const t = useTranslations('schedulesFeature.list');
  const state = scheduleRunState(status);
  const presentation = {
    pending: {
      label: t('statusPending'),
      icon: Clock3,
      className:
        'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200'
    },
    queued: {
      label: t('statusQueued'),
      icon: Clock3,
      className:
        'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200'
    },
    running: {
      label: t('statusRunning'),
      icon: CircleDashed,
      className:
        'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200'
    },
    completed: {
      label: t('statusCompleted'),
      icon: CheckCircle2,
      className:
        'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'
    },
    failed: {
      label: t('statusFailed'),
      icon: XCircle,
      className:
        'border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200'
    },
    cancelled: {
      label: t('statusCancelled'),
      icon: Ban,
      className: 'border-border bg-muted text-muted-foreground'
    },
    unknown: {
      label: status,
      icon: CircleDashed,
      className: 'border-border bg-muted text-muted-foreground'
    }
  }[state];
  const Icon = presentation.icon;

  return (
    <Badge
      variant='outline'
      className={cn('gap-1.5 font-medium', presentation.className, className)}
    >
      <Icon
        className={cn('size-3', state === 'running' && 'animate-spin')}
        aria-hidden
      />
      {presentation.label}
    </Badge>
  );
}

export function scheduleRunSourceLabel(
  source: string,
  t: (key: 'sourceManual' | 'sourceTemporal' | 'sourceScheduler') => string
) {
  const normalized = source.toLowerCase();
  if (['manual', 'run_now', 'run-now'].includes(normalized)) {
    return t('sourceManual');
  }
  if (normalized === 'temporal') return t('sourceTemporal');
  if (['scheduler', 'cron'].includes(normalized)) return t('sourceScheduler');
  return source;
}
