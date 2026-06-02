'use client';

import { useMemo, useState } from 'react';
import { CalendarIcon, ChevronDown } from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import type { DateRange } from 'react-day-picker';
import { vi, enUS } from 'date-fns/locale';
import { endOfDay, startOfDay } from 'date-fns';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import {
  ANALYTICS_RANGE_PRESETS,
  analyticsRangesEqual,
  dateRangeToIso,
  formatDateRangeLabel,
  lastNDaysDateRange,
  type AnalyticsDateRangeValue
} from '../lib/date-range';

export type AnalyticsDateRangeSelectProps = {
  value: AnalyticsDateRangeValue;
  onChange: (range: AnalyticsDateRangeValue) => void;
  className?: string;
};

function toDayPickerRange(value: AnalyticsDateRangeValue): DateRange {
  return { from: value.from, to: value.to ?? value.from };
}

function fromDayPickerRange(range: DateRange | undefined): AnalyticsDateRangeValue | null {
  if (!range?.from) return null;
  return {
    from: startOfDay(range.from),
    to: range.to ? endOfDay(range.to) : endOfDay(range.from)
  };
}

export function AnalyticsDateRangeSelect({
  value,
  onChange,
  className
}: AnalyticsDateRangeSelectProps) {
  const t = useTranslations('analyticsFeature.overview');
  const localeTag = useLocale();
  const calendarLocale = localeTag === 'vi' ? vi : enUS;
  const [open, setOpen] = useState(false);

  const label = useMemo(() => {
    for (const days of ANALYTICS_RANGE_PRESETS) {
      if (analyticsRangesEqual(value, lastNDaysDateRange(days))) {
        return t('windowOption', { days });
      }
    }
    const { from, to } = dateRangeToIso(value);
    return formatDateRangeLabel(from, to, localeTag);
  }, [value, localeTag, t]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          className={cn(
            'h-9 gap-1.5 px-3 font-normal shadow-none',
            className
          )}
        >
          <CalendarIcon className='size-4 shrink-0 text-muted-foreground' />
          <span className='max-w-[11rem] truncate'>{label}</span>
          <ChevronDown className='size-3.5 shrink-0 opacity-50' />
        </Button>
      </PopoverTrigger>
      <PopoverContent className='w-auto p-0' align='end'>
        <div className='flex flex-wrap gap-1 border-b p-2'>
          {ANALYTICS_RANGE_PRESETS.map((days) => {
            const preset = lastNDaysDateRange(days);
            const active = analyticsRangesEqual(value, preset);
            return (
              <Button
                key={days}
                type='button'
                variant={active ? 'secondary' : 'ghost'}
                size='sm'
                className='h-7 px-2.5 text-xs'
                onClick={() => {
                  onChange(preset);
                  setOpen(false);
                }}
              >
                {t('windowOption', { days })}
              </Button>
            );
          })}
        </div>
        <Calendar
          mode='range'
          locale={calendarLocale}
          selected={toDayPickerRange(value)}
          onSelect={(range) => {
            const next = fromDayPickerRange(range);
            if (next) onChange(next);
          }}
          numberOfMonths={1}
          initialFocus
        />
      </PopoverContent>
    </Popover>
  );
}
