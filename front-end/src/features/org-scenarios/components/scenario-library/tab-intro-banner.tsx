'use client';

import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

export function TabIntroBanner({
  icon: Icon,
  title,
  description,
  className
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  className?: string;
}) {
  return (
    <div className={cn('flex gap-3 rounded-lg border px-4 py-3', className)}>
      <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-background shadow-sm ring-1 ring-border/60'>
        <Icon className='size-4 text-muted-foreground' />
      </div>
      <div className='min-w-0 space-y-0.5'>
        <p className='text-sm font-medium text-foreground'>{title}</p>
        <p className='text-xs leading-relaxed text-muted-foreground'>
          {description}
        </p>
      </div>
    </div>
  );
}
