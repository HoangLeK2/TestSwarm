'use client';

import * as React from 'react';
import { useCallback, useRef, useState, useLayoutEffect } from 'react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

interface OverflowTooltipProps {
  children: React.ReactElement<any>;
  content?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  sideOffset?: number;
  delayDuration?: number;
  disabled?: boolean;
  asChild?: boolean;
}

export function OverflowTooltip({
  children,
  content,
  className,
  contentClassName,
  side = 'top',
  align = 'center',
  sideOffset = 4,
  delayDuration = 200,
  disabled = false,
  asChild = true
}: OverflowTooltipProps) {
  const [isOverflowing, setIsOverflowing] = useState(false);
  const elementRef = useRef<HTMLElement>(null);

  const checkOverflow = useCallback(() => {
    if (!elementRef.current) return;

    const element = elementRef.current;
    const isTextOverflowing = element.scrollWidth > element.clientWidth;
    setIsOverflowing(isTextOverflowing);
  }, []);

  useLayoutEffect(() => {
    checkOverflow();

    const resizeObserver = new ResizeObserver(checkOverflow);
    if (elementRef.current) {
      resizeObserver.observe(elementRef.current);
    }

    return () => resizeObserver.disconnect();
  }, [checkOverflow]);

  const childWithRef = React.cloneElement(children, {
    ref: elementRef,
    className: cn(children.props?.className, className)
  });

  // If not overflowing or disabled, return children without tooltip
  if (!isOverflowing || disabled) {
    return childWithRef;
  }

  return (
    <TooltipProvider delayDuration={delayDuration}>
      <Tooltip>
        <TooltipTrigger asChild={asChild}>{childWithRef}</TooltipTrigger>
        <TooltipContent
          side={side}
          align={align}
          sideOffset={sideOffset}
          className={cn('max-w-xs text-xs', contentClassName)}
        >
          {content || children.props?.children}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
