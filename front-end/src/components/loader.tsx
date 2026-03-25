import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export function Loader({
  title = 'Loading...',
  fullScreen = true,
  className
}: {
  title?: string;
  fullScreen?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex h-full w-full items-center justify-center',
        fullScreen && 'h-screen',
        className
      )}
    >
      <div className={cn('flex flex-col items-center space-y-4')}>
        <Loader2 className={cn('h-6 w-6 animate-spin')} />
        <span className={cn('text-lg font-semibold')}>{title}</span>
      </div>
    </div>
  );
}
