/* eslint-disable react/jsx-no-useless-fragment */
'use client';

import { Badge } from '@/components/ui/badge';
import { useTranslations } from 'next-intl';

interface HeaderProps {
  total: number;
  tasks: number;
  wsConnected: boolean;
  wifiDenseposeUrl?: string | null;
}

export function DeviceFarmHeader({
  total,
  tasks,
  wsConnected,
  wifiDenseposeUrl: _wifiDenseposeUrl
}: HeaderProps) {
  const t = useTranslations('devicesFarm.header');
  return (
    <header className='border-b bg-background px-4 py-2.5'>
      <div className='mx-auto flex max-w-7xl items-center gap-3'>
        <div className='flex flex-col gap-0.5 text-left'>
          <span className='text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground'>
            {t('eyebrow')}
          </span>
          <h1 className='text-sm font-semibold text-foreground'>{t('title')}</h1>
        </div>
        <div className='ml-auto flex items-center gap-2 text-[11px] text-muted-foreground'>
          <span className='inline-flex items-center gap-1 rounded-full border border-border bg-card/70 px-2 py-0.5'>
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                wsConnected ? 'bg-emerald-400' : 'animate-pulse bg-amber-400'
              }`}
            />
            <span id='ws-label' className='text-[10px]'>
              {wsConnected ? t('connected') : t('connecting')}
            </span>
          </span>
          <div className='hidden items-center gap-1.5 sm:flex'>
            <Badge id='stat-total' variant='outline' className='text-[10px]'>
              {t('devices', { count: total })}
            </Badge>
            <Badge
              id='stat-tasks'
              variant={tasks > 0 ? 'default' : 'outline'}
              className='text-[10px]'
            >
              {t('tasks', { count: tasks })}
            </Badge>
          </div>
        </div>
      </div>
    </header>
  );
}

