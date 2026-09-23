export type ScheduleCalendarPreviewItem = {
  id: string;
  name: string;
  cronExpression: string;
  timezone?: string | null;
  targetLabel?: string | null;
  isEnabled?: boolean;
};

export type Occurrence = {
  id: string;
  scheduleId: string;
  dayIndex: number;
  minuteOfDay: number;
  title: string;
  subtitle: string | null;
  colorClass: string;
  isEnabled: boolean;
};

export const DAY_COLUMNS = [
  { cronDow: 1, key: 'mon' },
  { cronDow: 2, key: 'tue' },
  { cronDow: 3, key: 'wed' },
  { cronDow: 4, key: 'thu' },
  { cronDow: 5, key: 'fri' },
  { cronDow: 6, key: 'sat' },
  { cronDow: 0, key: 'sun' }
] as const;

// Full day: a run at 00:00-05:59 must not silently disappear from the preview.
export const HOURS = Array.from({ length: 24 }, (_, index) => index);
export const HOUR_HEIGHT = 48;
// One run per hour fits without overlap; denser schedules are sampled and
// the remainder shows as the per-day "+N" badge.
const MAX_EVENTS_PER_DAY = 24;
export const VISUAL_EVENT_DURATION_MINUTES = 52;

const EVENT_COLORS = [
  'border-border border-l-sky-500 bg-sky-50/55 text-foreground hover:bg-sky-50 dark:border-l-sky-400 dark:bg-sky-950/25',
  'border-border border-l-emerald-500 bg-emerald-50/55 text-foreground hover:bg-emerald-50 dark:border-l-emerald-400 dark:bg-emerald-950/25',
  'border-border border-l-amber-500 bg-amber-50/55 text-foreground hover:bg-amber-50 dark:border-l-amber-400 dark:bg-amber-950/25',
  'border-border border-l-rose-500 bg-rose-50/50 text-foreground hover:bg-rose-50 dark:border-l-rose-400 dark:bg-rose-950/20',
  'border-border border-l-slate-500 bg-slate-50/70 text-foreground hover:bg-slate-100/70 dark:border-l-slate-400 dark:bg-slate-900/35'
];

export function pad2(value: number) {
  return String(value).padStart(2, '0');
}

// A box is taller than a minute, so placing it purely by minute pushes a
// 08:59 run into the 09:00 row. Keep it inside its own hour row: it slides
// down with the minute but its bottom never crosses the next hour line.
export function eventTop(
  minuteOfDay: number,
  hourHeight: number,
  boxHeight: number
) {
  const hourTop = (Math.floor(minuteOfDay / 60) - HOURS[0]) * hourHeight;
  const offset = ((minuteOfDay % 60) / 60) * hourHeight;
  return hourTop + Math.max(0, Math.min(offset, hourHeight - boxHeight));
}

function parseNumberField(field: string, min: number, max: number) {
  const values = new Set<number>();

  const addRange = (start: number, end: number, step = 1) => {
    if (step < 1 || start > end) return false;
    if (start < min || end > max) return false;
    for (let value = start; value <= end; value += step) {
      values.add(value);
    }
    return true;
  };

  for (const part of field.split(',')) {
    const trimmed = part.trim();
    if (!trimmed) return null;

    if (trimmed === '*') {
      if (!addRange(min, max)) return null;
      continue;
    }

    const stepMatch = trimmed.match(/^(.+)\/(\d+)$/);
    if (stepMatch) {
      const base = stepMatch[1];
      const step = Number(stepMatch[2]);
      if (base === '*') {
        if (!addRange(min, max, step)) return null;
        continue;
      }
      const range = base.match(/^(\d+)-(\d+)$/);
      if (!range) return null;
      if (!addRange(Number(range[1]), Number(range[2]), step)) return null;
      continue;
    }

    const range = trimmed.match(/^(\d+)-(\d+)$/);
    if (range) {
      if (!addRange(Number(range[1]), Number(range[2]))) return null;
      continue;
    }

    const number = Number(trimmed);
    if (!Number.isInteger(number) || number < min || number > max) return null;
    values.add(number);
  }

  return Array.from(values).sort((a, b) => a - b);
}

function parseDowField(field: string) {
  const parsed = parseNumberField(field, 0, 7);
  if (!parsed) return null;
  const normalized = parsed.map((value) => (value === 7 ? 0 : value));
  return new Set(normalized);
}

function sampleTimes(times: number[]) {
  if (times.length <= MAX_EVENTS_PER_DAY) return times;
  const stride = Math.ceil(times.length / MAX_EVENTS_PER_DAY);
  return times
    .filter((_, index) => index % stride === 0)
    .slice(0, MAX_EVENTS_PER_DAY);
}

export function buildOccurrences(schedules: ScheduleCalendarPreviewItem[]) {
  const occurrences: Occurrence[] = [];
  const overflowByDay = new Map<number, number>();
  let unsupportedCount = 0;

  schedules.forEach((schedule, scheduleIndex) => {
    const parts = schedule.cronExpression.trim().split(/\s+/);
    if (parts.length !== 5) {
      unsupportedCount += 1;
      return;
    }

    const [minuteField, hourField, dayOfMonthField, monthField, dowField] =
      parts;
    if (dayOfMonthField !== '*' || monthField !== '*') {
      unsupportedCount += 1;
      return;
    }

    const minutes = parseNumberField(minuteField, 0, 59);
    const hours = parseNumberField(hourField, 0, 23);
    const dows = parseDowField(dowField);
    if (!minutes || !hours || !dows) {
      unsupportedCount += 1;
      return;
    }

    const allTimes = hours.flatMap((hour) =>
      minutes.map((minute) => hour * 60 + minute)
    );
    const visibleTimes = sampleTimes(allTimes);

    DAY_COLUMNS.forEach((day, dayIndex) => {
      if (!dows.has(day.cronDow)) return;
      const overflow = Math.max(0, allTimes.length - visibleTimes.length);
      if (overflow > 0) {
        overflowByDay.set(
          dayIndex,
          (overflowByDay.get(dayIndex) ?? 0) + overflow
        );
      }

      visibleTimes.forEach((minuteOfDay) => {
        occurrences.push({
          id: `${schedule.id}-${day.key}-${minuteOfDay}`,
          scheduleId: schedule.id,
          dayIndex,
          minuteOfDay,
          title: schedule.name,
          subtitle: schedule.targetLabel ?? null,
          colorClass: EVENT_COLORS[scheduleIndex % EVENT_COLORS.length],
          isEnabled: schedule.isEnabled !== false
        });
      });
    });
  });

  return { occurrences, overflowByDay, unsupportedCount };
}
