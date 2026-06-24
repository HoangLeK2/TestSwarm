'use client';

import { CircleHelp } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Z_CAMPAIGN_MONITOR_FLOATING } from '@/lib/z-index';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';

interface Props {
  icon: React.ReactNode;
  title: string;
  hint: string;
  count: number;
  countVariant?: 'default' | 'secondary' | 'destructive';
  actions?: React.ReactNode;
}

export function MonitorSectionHeader({
  icon,
  title,
  hint,
  count,
  countVariant = 'secondary',
  actions
}: Props) {
  const t = useTranslations('campaignsFeature.list');

  return (
    <div className='min-w-0 space-y-2'>
      <div className='flex min-w-0 items-start justify-between gap-2'>
        <div className='flex min-w-0 items-center gap-2'>
          <span className='shrink-0 text-muted-foreground'>{icon}</span>
          <span className='min-w-0 text-base font-semibold leading-snug'>
            {title}
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type='button'
                className='shrink-0 rounded-full p-0.5 text-muted-foreground hover:text-foreground'
                aria-label={t('monitorSectionHintLabel')}
              >
                <CircleHelp size={18} />
              </button>
            </TooltipTrigger>
            <TooltipContent
              side='top'
              className='max-w-sm text-sm leading-snug'
              style={{ zIndex: Z_CAMPAIGN_MONITOR_FLOATING }}
            >
              {hint}
            </TooltipContent>
          </Tooltip>
        </div>
        <Badge
          variant={countVariant}
          className='min-h-7 shrink-0 px-2.5 text-sm tabular-nums'
        >
          {count}
        </Badge>
      </div>
      {actions ? (
        <div className='flex min-w-0 flex-wrap items-center gap-2'>
          {actions}
        </div>
      ) : null}
    </div>
  );
}
