'use client';

import { CircleHelp } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
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
    <div className='flex flex-wrap items-center gap-2.5'>
      <span className='text-muted-foreground'>{icon}</span>
      <span className='text-base font-semibold'>{title}</span>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type='button'
            className='rounded-full p-0.5 text-muted-foreground hover:text-foreground'
            aria-label={t('monitorSectionHintLabel')}
          >
            <CircleHelp size={18} />
          </button>
        </TooltipTrigger>
        <TooltipContent side='top' className='max-w-sm text-sm leading-snug'>
          {hint}
        </TooltipContent>
      </Tooltip>
      {actions ? <div className='ml-auto flex items-center gap-2'>{actions}</div> : null}
      <Badge
        variant={countVariant}
        className={cn(
          'min-h-7 min-w-7 justify-center px-2.5 text-sm tabular-nums',
          !actions && 'ml-auto'
        )}
      >
        {count}
      </Badge>
    </div>
  );
}
