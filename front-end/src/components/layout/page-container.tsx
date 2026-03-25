import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import React from 'react';

export default function PageContainer({
  children,
  scrollable = true,
  className
}: {
  children: React.ReactNode;
  scrollable?: boolean;
  className?: string;
}) {
  const containerClass = cn('h-full p-4 md:p-6', className);

  return (
    <>
      {scrollable ? (
        <ScrollArea className='h-[calc(100dvh-64px)]'>
          <div className={containerClass}>{children}</div>
        </ScrollArea>
      ) : (
        <div className={containerClass}>{children}</div>
      )}
    </>
  );
}

export function PageContainerContent({
  children,
  className
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex h-[calc(100dvh-64px)] flex-1 overflow-y-auto',
        className
      )}
    >
      {children}
    </div>
  );
}
