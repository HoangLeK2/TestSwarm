'use client';

import * as React from 'react';
import Image from 'next/image';
import { cn } from '@/lib/utils';

export function AuthLogo({
  variant = 'compact',
  className,
  imageClassName,
  textClassName
}: {
  variant?: 'compact' | 'full';
  className?: string;
  imageClassName?: string;
  textClassName?: string;
}) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <Image
        src='/logo.png'
        alt='logo'
        width={variant === 'compact' ? 120 : 160}
        height={48}
        className={cn('h-auto w-auto object-contain', imageClassName)}
        priority
      />
      {variant === 'full' ? (
        <span
          className={cn('text-sm font-medium text-foreground', textClassName)}
        >
          Device farm
        </span>
      ) : null}
    </div>
  );
}
