'use client';

import { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useRouter } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { AnalyticsDimension } from '../services/api';
import {
  dateRangeToIso,
  defaultAnalyticsDateRange,
  type AnalyticsDateRangeValue
} from '../lib/date-range';
import { ActivityFeed } from './activity-feed';
import { AnalyticsAuditPanel } from './analytics-audit-panel';
import { AnalyticsOverview } from './analytics-overview';
import { AnalyticsOverviewFilters } from './analytics-overview-filters';

type AnalyticsTab = 'overview' | 'activity' | 'audit';

function parseTab(value: string | null): AnalyticsTab {
  if (value === 'activity' || value === 'audit') return value;
  return 'overview';
}

export function AnalyticsDashboard() {
  const t = useTranslations('analyticsFeature.dashboard');
  const searchParams = useSearchParams();
  const router = useRouter();
  const tab = parseTab(searchParams.get('tab'));
  const [dateRange, setDateRange] = useState<AnalyticsDateRangeValue>(
    defaultAnalyticsDateRange
  );
  const [dimension, setDimension] = useState<AnalyticsDimension>('campaign');
  const isoRange = useMemo(() => dateRangeToIso(dateRange), [dateRange]);

  const setTab = useCallback(
    (next: AnalyticsTab) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === 'overview') params.delete('tab');
      else params.set('tab', next);
      const qs = params.toString();
      router.replace(
        qs ? `/dashboard/analytics?${qs}` : '/dashboard/analytics',
        { scroll: false }
      );
    },
    [router, searchParams]
  );

  return (
    <div className='space-y-4'>
      <div className='space-y-1'>
        <h1 className='text-xl font-bold tracking-tight text-foreground'>
          {t('title')}
        </h1>
        <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(parseTab(v))}>
        <div className='flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
          <TabsList className='h-auto w-fit flex-wrap'>
            <TabsTrigger value='overview' className='px-4'>
              {t('tabs.overview')}
            </TabsTrigger>
            <TabsTrigger value='activity' className='px-4'>
              {t('tabs.activity')}
            </TabsTrigger>
            <TabsTrigger value='audit' className='px-4'>
              {t('tabs.audit')}
            </TabsTrigger>
          </TabsList>
          {tab === 'overview' ? (
            <AnalyticsOverviewFilters
              dateRange={dateRange}
              onDateRangeChange={setDateRange}
              dimension={dimension}
              onDimensionChange={setDimension}
            />
          ) : null}
        </div>
        <TabsContent value='overview' className='mt-4'>
          <AnalyticsOverview range={isoRange} dimension={dimension} />
        </TabsContent>
        <TabsContent value='activity' className='mt-4'>
          <ActivityFeed embedded />
        </TabsContent>
        <TabsContent value='audit' className='mt-4'>
          <AnalyticsAuditPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
