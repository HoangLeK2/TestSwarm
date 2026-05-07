'use client';

import { useTranslations } from 'next-intl';
import { ActivityFeed } from './activity-feed';

export function DashboardActivity() {
  const t = useTranslations('analyticsFeature.dashboard');

  return (
    <div className='space-y-4'>
      <div>
        <h1 className='text-xl font-semibold tracking-tight'>{t('title')}</h1>
        <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
      </div>
      <ActivityFeed />
    </div>
  );
}
