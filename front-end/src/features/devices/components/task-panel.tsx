'use client';

import type { Task } from '../types';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useTranslations } from 'next-intl';

interface TaskPanelProps {
  tasks: Task[];
}

export function DeviceFarmTaskPanel({ tasks }: TaskPanelProps) {
  const t = useTranslations('devicesFarm.taskPanel');
  const taskList = Array.isArray(tasks) ? tasks : [];
  const pending = taskList.filter((t) =>
    ['PENDING', 'RUNNING', 'REQUEUED'].includes(t.status)
  );
  const items = taskList.slice(-20).reverse();

  return (
    <div className='fixed bottom-4 right-4 z-40 w-80 max-w-[90vw] text-left'>
      <Card className='border border-border bg-card/95 shadow-md backdrop-blur'>
        <CardHeader className='border-b border-border/60 px-4 py-2.5'>
          <CardTitle className='flex items-center justify-between text-xs'>
            <span className='font-semibold text-foreground'>{t('title')}</span>
            <Badge
              id='task-count'
              variant={pending.length > 0 ? 'secondary' : 'outline'}
              className='text-[10px]'
            >
              {t('pendingCount', { count: pending.length })}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className='px-3 py-2'>
          <div className='max-h-52 space-y-1.5 overflow-y-auto text-[11px]'>
            {items.length === 0 ? (
              <div className='text-xs text-muted-foreground'>
                {t('noTasks')}
              </div>
            ) : (
              items.map((task) => {
                const borderClass =
                  task.status === 'PENDING'
                    ? 'border-border'
                    : task.status === 'RUNNING'
                      ? 'border-amber-500/80 bg-amber-500/5'
                      : task.status === 'DONE'
                        ? 'border-emerald-500/80 bg-emerald-500/5'
                        : task.status === 'FAILED'
                          ? 'border-destructive/80 bg-destructive/5'
                          : 'border-sky-500/80 bg-sky-500/5';
                return (
                  <div
                    key={task.id}
                    className={`rounded-md border-l-2 px-2 py-1 ${borderClass}`}
                  >
                    <div className='flex items-center justify-between gap-2'>
                      <span className='truncate font-medium text-foreground'>
                        {task.name || task.id.slice(0, 8)}
                      </span>
                      <span className='text-[10px] uppercase tracking-wide text-muted-foreground'>
                        {task.status}
                      </span>
                    </div>
                    <div className='mt-0.5 text-[10px] text-muted-foreground'>
                      {task.target ? '@' + task.target : t('any')} ·{' '}
                      {t('retry')} {task.retry_count}/{task.max_retries}
                      {task.error && (
                        <span className='ml-1 text-destructive'>
                          · {task.error.slice(0, 40)}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
