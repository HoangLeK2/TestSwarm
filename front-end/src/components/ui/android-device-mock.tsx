import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

type AndroidDeviceMockProps = {
  children: ReactNode;
  width: number;
  height: number;
  compact?: boolean;
  className?: string;
};

export function AndroidDeviceMock({
  children,
  width,
  height,
  compact = false,
  className
}: AndroidDeviceMockProps) {
  return (
    <div
      className={cn(
        'group relative rounded-[2rem] border border-white/10 bg-gradient-to-b from-zinc-900/90 to-zinc-950/95 p-[5px] shadow-[0_12px_36px_rgba(59,130,246,0.16)]',
        compact ? 'rounded-[1.5rem] p-1' : '',
        className
      )}
    >
      <div
        className={cn(
          'pointer-events-none absolute inset-0 rounded-[inherit] bg-[radial-gradient(120%_60%_at_50%_0%,rgba(255,255,255,0.14),transparent_55%)]'
        )}
      />
      <div
        className={cn(
          'pointer-events-none absolute left-1/2 top-[7px] z-10 -translate-x-1/2 rounded-full bg-zinc-700/80',
          compact ? 'h-[2px] w-8' : 'h-[2px] w-10'
        )}
      />
      <div
        className={cn(
          'relative overflow-hidden rounded-[1.6rem] border border-white/5 bg-black',
          compact ? 'rounded-[1.15rem]' : ''
        )}
        style={{ width: `${width}px`, height: `${height}px` }}
      >
        <div className='pointer-events-none absolute inset-0 z-10 bg-[radial-gradient(100%_45%_at_50%_0%,rgba(255,255,255,0.08),transparent_60%)]' />
        {children}
      </div>
    </div>
  );
}
