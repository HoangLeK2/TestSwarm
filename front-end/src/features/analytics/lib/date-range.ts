import {
  differenceInCalendarDays,
  endOfDay,
  isSameDay,
  startOfDay,
  subDays
} from 'date-fns';

export type AnalyticsDateRangeValue = {
  from: Date;
  to: Date | undefined;
};

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Default overview range: last 7 calendar days through today. */
export function defaultAnalyticsDateRange(): AnalyticsDateRangeValue {
  return lastNDaysDateRange(7);
}

export function lastNDaysDateRange(days: number): AnalyticsDateRangeValue {
  const safeDays = Math.min(Math.max(days, 1), 90);
  return {
    from: startOfDay(subDays(new Date(), safeDays - 1)),
    to: endOfDay(new Date())
  };
}

export function analyticsRangesEqual(
  a: AnalyticsDateRangeValue,
  b: AnalyticsDateRangeValue
): boolean {
  const aEnd = a.to ?? a.from;
  const bEnd = b.to ?? b.from;
  return isSameDay(a.from, b.from) && isSameDay(aEnd, bEnd);
}

export const ANALYTICS_RANGE_PRESETS = [7, 14, 30, 90] as const;

export function dateRangeToIso(range: AnalyticsDateRangeValue): {
  from: string;
  to: string;
} {
  const end = range.to ?? range.from;
  return { from: isoDate(range.from), to: isoDate(end) };
}

export function inclusiveDayCount(from: string, to: string): number {
  const start = new Date(`${from}T12:00:00`);
  const end = new Date(`${to}T12:00:00`);
  return Math.min(90, Math.max(1, differenceInCalendarDays(end, start) + 1));
}

export function lastNDaysRange(days: number): { from: string; to: string } {
  const end = new Date();
  const start = new Date();
  start.setUTCDate(end.getUTCDate() - (days - 1));
  return { from: isoDate(start), to: isoDate(end) };
}

export function formatChartDate(iso: string, locale?: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
}

/** Human-readable range for filter toolbar, e.g. "26 thg 5 – 1 thg 6, 2026". */
export function formatDateRangeLabel(
  from: string,
  to: string,
  locale?: string
): string {
  const opts: Intl.DateTimeFormatOptions = {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  };
  const fmt = new Intl.DateTimeFormat(locale, opts);
  const start = fmt.format(new Date(`${from}T12:00:00`));
  if (from === to) return start;
  const end = fmt.format(new Date(`${to}T12:00:00`));
  return `${start} – ${end}`;
}
