'use client';

import dynamic from 'next/dynamic';
import { useEffect, useMemo, useState } from 'react';
import { useTheme } from 'next-themes';
import type { EChartsOption } from 'echarts';
import { cn } from '@/lib/utils';
import {
  readAnalyticsChartTheme,
  type AnalyticsChartTheme
} from '../lib/chart-theme';

const ReactECharts = dynamic(() => import('echarts-for-react'), { ssr: false });

export type AnalyticsTimeseriesPoint = {
  label: string;
  count: number;
  fail_count: number;
};

type Props = {
  data: AnalyticsTimeseriesPoint[];
  seriesLabels: { total: string; failures: string };
  className?: string;
};

function buildOption(
  data: AnalyticsTimeseriesPoint[],
  seriesLabels: { total: string; failures: string },
  theme: AnalyticsChartTheme
): EChartsOption {
  return {
    animation: true,
    grid: { left: 48, right: 16, top: 16, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' }
    },
    legend: {
      bottom: 0,
      textStyle: { color: theme.mutedForeground }
    },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.label),
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { show: false },
      axisLabel: { color: theme.mutedForeground, margin: 8 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: theme.mutedForeground, width: 40 },
      splitLine: { lineStyle: { color: theme.border, opacity: 0.5 } }
    },
    series: [
      {
        name: seriesLabels.total,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: data.map((d) => d.count),
        lineStyle: { width: 2, color: theme.total },
        itemStyle: { color: theme.total }
      },
      {
        name: seriesLabels.failures,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: data.map((d) => d.fail_count),
        lineStyle: { width: 2, color: theme.failures },
        itemStyle: { color: theme.failures }
      }
    ]
  };
}

export function AnalyticsTimeseriesChart({
  data,
  seriesLabels,
  className
}: Props) {
  const { resolvedTheme } = useTheme();
  const [theme, setTheme] = useState<AnalyticsChartTheme>(() => ({
    total: 'hsl(var(--chart-1))',
    failures: 'hsl(var(--chart-5))',
    mutedForeground: 'hsl(var(--muted-foreground))',
    border: 'hsl(var(--border))'
  }));

  useEffect(() => {
    setTheme(readAnalyticsChartTheme());
  }, [resolvedTheme]);

  const option = useMemo(
    () => buildOption(data, seriesLabels, theme),
    [data, seriesLabels, theme]
  );

  return (
    <div className={cn('h-[220px] w-full', className)}>
      <ReactECharts
        option={option}
        notMerge
        lazyUpdate
        style={{ height: '100%', width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}
