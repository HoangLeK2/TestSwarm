import { cn } from '@/lib/utils';
import { ReactNode } from 'react';

interface DataTableEmptyProps {
  title: string;
  description?: string;
  children?: ReactNode;
  className?: string;
}

export function DataTableEmpty({
  title,
  description,
  children,
  className
}: DataTableEmptyProps) {
  return (
    <div
      className={cn(
        'flex h-full min-h-[400px] w-full items-center justify-center',
        className
      )}
    >
      <div className='flex flex-col items-center gap-4'>
        <img
          src='/assets/no-data.svg'
          alt='No Product'
          className='mx-auto w-32'
        />
        <div className='flex flex-col items-center'>
          <p className='text-center text-lg font-medium'>{title}</p>
          {description && (
            <p className='text-center text-sm text-muted-foreground/80'>
              {description}
            </p>
          )}
        </div>
        {children && <div className='flex gap-2'>{children}</div>}
      </div>
    </div>
  );
}
