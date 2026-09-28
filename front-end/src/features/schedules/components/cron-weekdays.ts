export const CRON_WEEKDAYS = [
  { value: 1, labelKey: 'weekdayMon', fallback: 'Mon' },
  { value: 2, labelKey: 'weekdayTue', fallback: 'Tue' },
  { value: 3, labelKey: 'weekdayWed', fallback: 'Wed' },
  { value: 4, labelKey: 'weekdayThu', fallback: 'Thu' },
  { value: 5, labelKey: 'weekdayFri', fallback: 'Fri' },
  { value: 6, labelKey: 'weekdaySat', fallback: 'Sat' },
  { value: 0, labelKey: 'weekdaySun', fallback: 'Sun' }
] as const;

const CALENDAR_ORDER = CRON_WEEKDAYS.map(({ value }) => value);

function normalizeCronWeekday(value: number) {
  if (!Number.isInteger(value) || value < 0 || value > 7) return null;
  return value === 7 ? 0 : value;
}

export function orderCronWeekdays(values: number[]) {
  const normalized = new Set<number>();

  for (const value of values) {
    const weekday = normalizeCronWeekday(value);
    if (weekday === null) continue;
    normalized.add(weekday);
  }

  return CALENDAR_ORDER.filter((value) => normalized.has(value));
}

export function parseCronWeekdays(field: string): number[] | null {
  if (!field || field === '*') return null;

  const values: number[] = [];
  for (const rawPart of field.split(',')) {
    const part = rawPart.trim();
    if (!part) return null;

    const range = part.match(/^(\d)-(\d)$/);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      if (start > end || start < 0 || end > 7) return null;
      for (let value = start; value <= end; value += 1) values.push(value);
      continue;
    }

    if (!/^\d$/.test(part)) return null;
    values.push(Number(part));
  }

  const ordered = orderCronWeekdays(values);
  return ordered.length > 0 ? ordered : null;
}

export function formatCronWeekdays(values: number[]) {
  return orderCronWeekdays(values).join(',');
}
