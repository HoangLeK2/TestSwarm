'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  LineChart,
  Percent,
  XCircle
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { CoreEmptyState } from '@/components/core-empty-state';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { DatePicker } from '@/components/ui/date-time-picker/date-picker';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  useAnalyticsAdhocQuery,
  useAnalyticsSummary,
  useAnalyticsTimeseries
} from '../hooks/use-analytics';
import { formatChartDate, inclusiveDayCount, isoDate } from '../lib/date-range';
import type { AnalyticsDimension } from '../services/api';
import { AnalyticsKpiCard } from './analytics-kpi-card';
import { AnalyticsTimeseriesChart } from './analytics-timeseries-chart';

export type AnalyticsOverviewProps = {
  range: { from: string; to: string };
  dimension: AnalyticsDimension;
};

export function AnalyticsOverview({ range, dimension }: AnalyticsOverviewProps) {
  const t = useTranslations('analyticsFeature.overview');
  const locale = useLocale();
  const { currentOrg } = useOrganization();
  const [adhocOpen, setAdhocOpen] = useState(false);
  const windowDays = useMemo(
    () => inclusiveDayCount(range.from, range.to),
    [range.from, range.to]
  );

  const {
    data: summary,
    isLoading: summaryLoading,
    isError: summaryError,
    refetch: refetchSummary
  } = useAnalyticsSummary(windowDays);
  const {
    data: series,
    isLoading: seriesLoading,
    isError: seriesError,
    refetch: refetchSeries
  } = useAnalyticsTimeseries({
    dimension,
    from: range.from,
    to: range.to,
    granularity: 'day'
  });

  const adhoc = useAnalyticsAdhocQuery();
  const [adhocFrom, setAdhocFrom] = useState(range.from);
  const [adhocTo, setAdhocTo] = useState(range.to);

  useEffect(() => {
    setAdhocFrom(range.from);
    setAdhocTo(range.to);
  }, [range.from, range.to]);

  const chartData = useMemo(() => {
    const byDate = new Map<
      string,
      { date: string; count: number; fail_count: number }
    >();
    for (const point of series?.points ?? []) {
      const existing = byDate.get(point.date) ?? {
        date: point.date,
        count: 0,
        fail_count: 0
      };
      existing.count += point.count;
      existing.fail_count += point.fail_count;
      byDate.set(point.date, existing);
    }
    return Array.from(byDate.values())
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((row) => ({
        ...row,
        label: formatChartDate(row.date, locale)
      }));
  }, [series?.points, locale]);

  const hasOrg = Boolean(currentOrg?.id);
  const loadError = summaryError || seriesError;
  const hasChartData = chartData.length > 0;
  const hasSummaryData =
    summary != null &&
    (summary.total_count > 0 ||
      summary.success_count > 0 ||
      summary.fail_count > 0);
  const showGlobalEmpty =
    hasOrg && !summaryLoading && !seriesLoading && !loadError && !hasChartData && !hasSummaryData;

  const successRateDisplay =
    summary != null ? `${(summary.success_rate * 100).toFixed(1)}%` : undefined;

  const runAdhoc = () => {
    adhoc.mutate({
      from: adhocFrom,
      to: adhocTo,
      dimensions: ['day', 'event_type'],
      metric: 'count',
      limit: 200
    });
  };

  return (
    <div className='space-y-6'>
      {!hasOrg ? (
        <Alert>
          <AlertCircle className='size-4' />
          <AlertTitle>{t('noOrgTitle')}</AlertTitle>
          <AlertDescription>{t('noOrgDescription')}</AlertDescription>
        </Alert>
      ) : null}

      {loadError ? (
        <Alert variant='destructive'>
          <AlertCircle className='size-4' />
          <AlertTitle>{t('loadErrorTitle')}</AlertTitle>
          <AlertDescription className='flex flex-wrap items-center gap-3'>
            <span>{t('loadErrorDescription')}</span>
            <Button
              type='button'
              size='sm'
              variant='outline'
              className='h-8'
              onClick={() => {
                void refetchSummary();
                void refetchSeries();
              }}
            >
              {t('retry')}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {showGlobalEmpty ? (
        <CoreEmptyState
          icon={BarChart3}
          title={t('emptyTitle')}
          description={t('emptyDescription')}
          cta={{ label: t('emptyCtaCampaigns'), href: '/dashboard/campaigns' }}
          secondaryCta={{
            label: t('emptyCtaActivity'),
            href: '/dashboard/analytics?tab=activity'
          }}
          trackingKey='analytics-overview-empty'
        />
      ) : null}

      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
        <AnalyticsKpiCard
          label={t('stats.total')}
          icon={Activity}
          tone='neutral'
          loading={summaryLoading}
          value={summary?.total_count ?? (summaryLoading ? undefined : 0)}
        />
        <AnalyticsKpiCard
          label={t('stats.success')}
          icon={CheckCircle2}
          tone='success'
          loading={summaryLoading}
          value={summary?.success_count ?? (summaryLoading ? undefined : 0)}
        />
        <AnalyticsKpiCard
          label={t('stats.failures')}
          icon={XCircle}
          tone='danger'
          loading={summaryLoading}
          value={summary?.fail_count ?? (summaryLoading ? undefined : 0)}
        />
        <AnalyticsKpiCard
          label={t('stats.successRate')}
          icon={Percent}
          tone='accent'
          loading={summaryLoading}
          value={successRateDisplay ?? (summaryLoading ? undefined : '0%')}
        />
      </div>

      {!showGlobalEmpty ? (
        <Card>
          <CardHeader className='pb-2'>
            <div className='flex items-center gap-2'>
              <LineChart className='size-4 text-muted-foreground' />
              <CardTitle className='text-base'>{t('timeseriesTitle')}</CardTitle>
            </div>
            <CardDescription>{t('timeseriesHint')}</CardDescription>
          </CardHeader>
          <CardContent>
            {seriesLoading ? (
              <div className='space-y-3 py-4'>
                <Skeleton className='h-[220px] w-full rounded-lg' />
              </div>
            ) : !hasChartData ? (
              <CoreEmptyState
                icon={LineChart}
                title={t('chartEmptyTitle')}
                description={t('chartEmptyDescription')}
                variant='no-results'
                className='border-0 bg-transparent py-8'
                secondaryCta={{
                  label: t('emptyCtaActivity'),
                  href: '/dashboard/analytics?tab=activity'
                }}
                trackingKey='analytics-chart-empty'
              />
            ) : (
              <AnalyticsTimeseriesChart
                data={chartData}
                seriesLabels={{
                  total: t('stats.total'),
                  failures: t('stats.failures')
                }}
              />
            )}
          </CardContent>
        </Card>
      ) : null}

      <Collapsible open={adhocOpen} onOpenChange={setAdhocOpen}>
        <Card>
          <CollapsibleTrigger asChild>
            <button
              type='button'
              className='flex w-full items-center justify-between gap-2 px-6 py-4 text-left hover:bg-muted/30'
            >
              <div>
                <p className='text-sm font-semibold text-foreground'>
                  {t('adhocTitle')}
                </p>
                <p className='mt-0.5 text-xs text-muted-foreground'>
                  {t('adhocHint')}
                </p>
              </div>
              <ChevronDown
                className={`size-4 shrink-0 text-muted-foreground transition-transform ${adhocOpen ? 'rotate-180' : ''}`}
              />
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent className='space-y-4 border-t pt-4'>
              <div className='flex flex-wrap items-end gap-3'>
                <div className='space-y-1.5'>
                  <Label htmlFor='adhoc-from'>{t('from')}</Label>
                  <DatePicker
                    value={adhocFrom}
                    onChange={(date) => {
                      if (date) setAdhocFrom(isoDate(date));
                    }}
                    className='w-[200px]'
                  />
                </div>
                <div className='space-y-1.5'>
                  <Label htmlFor='adhoc-to'>{t('to')}</Label>
                  <DatePicker
                    value={adhocTo}
                    onChange={(date) => {
                      if (date) setAdhocTo(isoDate(date));
                    }}
                    className='w-[200px]'
                  />
                </div>
                <Button
                  onClick={runAdhoc}
                  disabled={adhoc.isPending || !hasOrg}
                  className='mb-0.5'
                >
                  {t('runQuery')}
                </Button>
              </div>
              {adhoc.isPending ? (
                <div className='space-y-2'>
                  <Skeleton className='h-8 w-full' />
                  <Skeleton className='h-8 w-full' />
                  <Skeleton className='h-8 w-2/3' />
                </div>
              ) : adhoc.data && adhoc.data.rows.length > 0 ? (
                <div className='overflow-x-auto rounded-lg border'>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        {Object.keys(adhoc.data.rows[0] ?? {}).map((key) => (
                          <TableHead key={key} className='whitespace-nowrap text-xs'>
                            {key}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {adhoc.data.rows.slice(0, 50).map((row: Record<string, unknown>, idx: number) => (
                        <TableRow key={idx}>
                          {Object.entries(row).map(([key, value]) => (
                            <TableCell
                              key={key}
                              className='tabular-nums text-sm'
                            >
                              {value == null ? '—' : String(value)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {adhoc.data.rows.length > 50 ? (
                    <p className='border-t px-3 py-2 text-xs text-muted-foreground'>
                      {t('adhocTruncated', { count: 50 })}
                    </p>
                  ) : null}
                </div>
              ) : adhoc.isSuccess ? (
                <p className='text-sm text-muted-foreground'>{t('adhocEmpty')}</p>
              ) : null}
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  );
}
