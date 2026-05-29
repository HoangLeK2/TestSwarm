'use client';

import { cn } from '@/lib/utils';

export function FlowStepRail({
  stepNumber,
  showLine = true,
  nested = false
}: {
  stepNumber?: number;
  showLine?: boolean;
  nested?: boolean;
}) {
  if (nested) {
    return (
      <div
        className='mr-1 w-px shrink-0 self-stretch bg-border/60'
        aria-hidden
      />
    );
  }

  return (
    <div
      className='flex w-7 shrink-0 flex-col items-center pt-1.5'
      aria-hidden={stepNumber == null}
    >
      {stepNumber != null ? (
        <span
          className={cn(
            'flex size-6 items-center justify-center rounded-full',
            'border border-border/80 bg-muted/40 text-[10px] font-semibold tabular-nums text-muted-foreground'
          )}
        >
          {stepNumber}
        </span>
      ) : (
        <span className='size-6 shrink-0' />
      )}
      {showLine && (
        <div className='mt-1 min-h-[10px] w-px flex-1 bg-border/60' />
      )}
    </div>
  );
}
