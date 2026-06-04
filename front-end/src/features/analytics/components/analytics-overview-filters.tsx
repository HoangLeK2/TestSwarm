'use client';

import { useTranslations } from 'next-intl';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import type { AnalyticsDateRangeValue } from '../lib/date-range';
import type { AnalyticsDimension } from '../services/api';
import { AnalyticsDateRangeSelect } from './analytics-date-range-select';

const DIMENSIONS = [
  'campaign',
  'device',
  'platform',
  'account',
  'event_type'
] as const satisfies readonly AnalyticsDimension[];

export type AnalyticsOverviewFiltersProps = {
  dateRange: AnalyticsDateRangeValue;
  onDateRangeChange: (range: AnalyticsDateRangeValue) => void;
  dimension: AnalyticsDimension;
  onDimensionChange: (dimension: AnalyticsDimension) => void;
};

export function AnalyticsOverviewFilters({
  dateRange,
  onDateRangeChange,
  dimension,
  onDimensionChange
}: AnalyticsOverviewFiltersProps) {
  const t = useTranslations('analyticsFeature.overview');

  return (
    <div
      className='flex flex-wrap items-center gap-2'
      aria-label={t('filtersTitle')}
    >
      <AnalyticsDateRangeSelect
        value={dateRange}
        onChange={onDateRangeChange}
      />
      <Select
        value={dimension}
        onValueChange={(v) => onDimensionChange(v as AnalyticsDimension)}
      >
        <SelectTrigger
          id='analytics-dimension'
          className='h-9 w-auto min-w-[168px] gap-2 shadow-none'
          aria-label={t('dimension')}
        >
          <span className='text-xs text-muted-foreground'>
            {t('dimension')}
          </span>
          <SelectValue />
        </SelectTrigger>
        <SelectContent align='end'>
          {DIMENSIONS.map((d) => (
            <SelectItem key={d} value={d}>
              {t(`dimensions.${d}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
