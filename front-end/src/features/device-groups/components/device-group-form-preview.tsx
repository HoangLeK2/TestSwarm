'use client';

import { Badge } from '@/components/ui/badge';
import { sanitizeHex } from '@/components/ui/hex-color-popover';
import { cn } from '@/lib/utils';

type Props = {
  name: string;
  description?: string;
  color: string;
  deviceCount: number;
  title: string;
  caption: string;
  emptyNameLabel: string;
  dashLabel: string;
  /** e.g. "Devices" for badge aria */
  devicesLabel: string;
};

export function DeviceGroupFormPreview({
  name,
  description,
  color,
  deviceCount,
  title,
  caption,
  emptyNameLabel,
  dashLabel,
  devicesLabel
}: Props) {
  const trimmedName = name.trim();
  const displayName = trimmedName || emptyNameLabel;
  const desc = (description ?? '').trim();

  return (
    <div className='space-y-2 rounded-lg border bg-muted/40 p-3'>
      <div className='space-y-0.5'>
        <p className='text-xs font-semibold leading-tight'>{title}</p>
        <p className='text-[11px] leading-snug text-muted-foreground'>
          {caption}
        </p>
      </div>
      <div
        className='rounded-md border bg-background p-3 shadow-sm transition-colors'
        aria-label={title}
      >
        <div className='flex items-center gap-3'>
          <div
            className='size-4 shrink-0 rounded-full ring-1 ring-border'
            style={{ backgroundColor: sanitizeHex(color) }}
            aria-hidden
          />
          <div className='min-w-0 flex-1'>
            <p
              className={cn(
                'truncate text-sm font-semibold',
                !trimmedName && 'italic text-muted-foreground'
              )}
            >
              {displayName}
            </p>
            <p className='truncate text-sm text-muted-foreground'>
              {desc || dashLabel}
            </p>
          </div>
          <Badge
            variant='secondary'
            className='shrink-0 tabular-nums'
            title={`${devicesLabel}: ${deviceCount}`}
          >
            {deviceCount}
          </Badge>
        </div>
      </div>
    </div>
  );
}
