'use client';

import { useLocale, useTranslations } from 'next-intl';
import { DateRangePicker } from '@/components/ui/date-range-picker';
import {
  DEFAULT_DATE_RANGE,
  useDateRange
} from '@/features/overview/providers/date-range-provider';
import { vi, enUS } from 'date-fns/locale';

export function DateRangeFilter() {
  const tCommon = useTranslations('common.datePicker');
  const { dateRange, setDateRange } = useDateRange();
  const locale = useLocale();
  const parsedLocale = locale === 'vi' ? vi : enUS;

  return (
    <DateRangePicker
      value={dateRange as any}
      onValueChange={setDateRange}
      onClear={() => setDateRange(DEFAULT_DATE_RANGE)}
      placeholder={tCommon('selectDateRange')}
      className='min-w-72'
      size='default'
      locale={parsedLocale}
      showCompare={false}
    />
  );
}
