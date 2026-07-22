'use client';

import * as React from 'react';
import { Info } from 'lucide-react';
import {
  Tooltip as UITooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

interface TooltipProps {
  content: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  wrapperClassName?: string;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  sideOffset?: number;
  delayDuration?: number;
  showIcon?: boolean;
  iconClassName?: string;
  titleClassName?: string;
  title?: React.ReactNode;
}

export function TitleTooltip({
  content,
  children,
  className,
  contentClassName,
  wrapperClassName,
  side = 'top',
  align = 'center',
  sideOffset = 4,
  delayDuration = 200,
  showIcon = true,
  iconClassName,
  titleClassName,
  title
}: TooltipProps) {
  return (
    <div
      className={cn(
        'flex items-start gap-1',
        !!wrapperClassName && wrapperClassName
      )}
    >
      <div className={cn(titleClassName)}>{title}</div>
      <TooltipProvider delayDuration={delayDuration}>
        <UITooltip>
          <TooltipTrigger asChild>
            {children ?? (
              <span
                className={cn(
                  'inline-flex cursor-help items-center',
                  className
                )}
                onClick={(event) => event.stopPropagation()}
                onPointerDown={(event) => event.stopPropagation()}
              >
                {showIcon ? (
                  <Info
                    className={cn(
                      'h-4 w-4 text-muted-foreground',
                      iconClassName
                    )}
                    aria-hidden
                  />
                ) : null}
              </span>
            )}
          </TooltipTrigger>
          <TooltipContent
            side={side}
            align={align}
            sideOffset={sideOffset}
            className={cn('max-w-xs text-xs shadow-lg', contentClassName)}
          >
            {content}
          </TooltipContent>
        </UITooltip>
      </TooltipProvider>
    </div>
  );
}
