'use client';

import { CalendarClock } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type ScheduleCalendarPreviewItem = {
  id: string;
  name: string;
  cronExpression: string;
  timezone?: string | null;
  targetLabel?: string | null;
  isEnabled?: boolean;
};

type Occurrence = {
  id: string;
  scheduleId: string;
  dayIndex: number;
  minuteOfDay: number;
  title: string;
  subtitle: string | null;
  colorClass: string;
  isEnabled: boolean;
};

const DAY_COLUMNS = [
  { cronDow: 1, key: 'mon' },
  { cronDow: 2, key: 'tue' },
  { cronDow: 3, key: 'wed' },
  { cronDow: 4, key: 'thu' },
  { cronDow: 5, key: 'fri' },
  { cronDow: 6, key: 'sat' },
  { cronDow: 0, key: 'sun' }
] as const;

const HOURS = Array.from({ length: 18 }, (_, index) => index + 6);
const HOUR_HEIGHT = 48;
const MAX_EVENTS_PER_DAY = 8;

const EVENT_COLORS = [
  'border-sky-500/35 bg-sky-500/15 text-sky-950 dark:text-sky-100',
  'border-emerald-500/35 bg-emerald-500/15 text-emerald-950 dark:text-emerald-100',
  'border-amber-500/40 bg-amber-500/15 text-amber-950 dark:text-amber-100',
  'border-rose-500/35 bg-rose-500/15 text-rose-950 dark:text-rose-100',
  'border-cyan-500/35 bg-cyan-500/15 text-cyan-950 dark:text-cyan-100',
  'border-fuchsia-500/35 bg-fuchsia-500/15 text-fuchsia-950 dark:text-fuchsia-100'
];

function pad2(value: number) {
  return String(value).padStart(2, '0');
}

function formatTime(minuteOfDay: number) {
  const hour = Math.floor(minuteOfDay / 60);
  const minute = minuteOfDay % 60;
  return `${pad2(hour)}:${pad2(minute)}`;
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

function buildOccurrences(schedules: ScheduleCalendarPreviewItem[]) {
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

export function ScheduleCalendarPreview({
  schedules,
  compact = false,
  className,
  onSelectSchedule
}: {
  schedules: ScheduleCalendarPreviewItem[];
  compact?: boolean;
  className?: string;
  onSelectSchedule?: (scheduleId: string) => void;
}) {
  const t = useTranslations('schedulesFeature.preview');
  const { occurrences, overflowByDay, unsupportedCount } =
    buildOccurrences(schedules);
  const hasItems = schedules.length > 0;
  const hourHeight = compact ? HOUR_HEIGHT : 72;
  const gridHeight = HOURS.length * hourHeight;

  return (
    <section className={cn('rounded-lg border bg-background', className)}>
      <div
        className={cn(
          'flex flex-wrap items-start justify-between gap-3 border-b',
          compact ? 'p-3' : 'p-4'
        )}
      >
        <div className='min-w-0'>
          <div className='flex items-center gap-2'>
            <CalendarClock
              className={cn(
                'text-muted-foreground',
                compact ? 'size-4' : 'size-5'
              )}
            />
            <h3
              className={cn('font-semibold', compact ? 'text-sm' : 'text-lg')}
            >
              {t('title')}
            </h3>
          </div>
          <p className='mt-1 text-xs text-muted-foreground'>
            {compact ? t('compactSubtitle') : t('subtitle')}
          </p>
        </div>
        <div className='flex flex-wrap gap-2'>
          <Badge variant='outline' className='h-6 text-[11px]'>
            {t('scheduleCount', { count: schedules.length })}
          </Badge>
          {unsupportedCount > 0 && (
            <Badge variant='secondary' className='h-6 text-[11px]'>
              {t('unsupportedCount', { count: unsupportedCount })}
            </Badge>
          )}
        </div>
      </div>

      {!hasItems ? (
        <div className='p-6 text-center text-sm text-muted-foreground'>
          {t('empty')}
        </div>
      ) : (
        <div
          className={cn(
            'overflow-auto',
            compact ? 'max-h-[26rem]' : 'max-h-[calc(100vh-14rem)]'
          )}
        >
          <div className={compact ? 'min-w-full' : 'min-w-[980px]'}>
            <div
              className={cn(
                'grid border-b bg-muted/35 font-medium text-muted-foreground',
                compact
                  ? 'grid-cols-[3.5rem_repeat(7,minmax(0,1fr))] text-[11px]'
                  : 'grid-cols-[5rem_repeat(7,minmax(0,1fr))] text-xs'
              )}
            >
              <div className='border-r px-2 py-2'>{t('time')}</div>
              {DAY_COLUMNS.map((day) => (
                <div
                  key={day.key}
                  className='border-r px-2 py-2 last:border-r-0'
                >
                  {t(`days.${day.key}`)}
                </div>
              ))}
            </div>

            <div
              className={cn(
                'relative grid',
                compact
                  ? 'grid-cols-[3.5rem_repeat(7,minmax(0,1fr))]'
                  : 'grid-cols-[5rem_repeat(7,minmax(0,1fr))]'
              )}
              style={{ height: gridHeight }}
            >
              <div className='relative border-r bg-muted/20'>
                {HOURS.map((hour) => (
                  <div
                    key={hour}
                    className={cn(
                      'border-b px-2 pt-1 text-muted-foreground',
                      compact ? 'text-[10px]' : 'text-xs'
                    )}
                    style={{ height: hourHeight }}
                  >
                    {pad2(hour)}:00
                  </div>
                ))}
              </div>

              {DAY_COLUMNS.map((day, dayIndex) => (
                <div
                  key={day.key}
                  className='relative border-r last:border-r-0'
                >
                  {HOURS.map((hour) => (
                    <div
                      key={hour}
                      className='border-b border-dashed border-border/80'
                      style={{ height: hourHeight }}
                    />
                  ))}

                  {occurrences
                    .filter((occurrence) => occurrence.dayIndex === dayIndex)
                    .map((occurrence) => {
                      const top =
                        ((occurrence.minuteOfDay - HOURS[0] * 60) / 60) *
                        hourHeight;
                      if (top < 0 || top > gridHeight - 22) return null;

                      const content = (
                        <>
                          <div className='font-semibold'>
                            {formatTime(occurrence.minuteOfDay)}
                          </div>
                          {!compact && (
                            <div className='truncate'>{occurrence.title}</div>
                          )}
                          {!compact && occurrence.subtitle && (
                            <div className='truncate text-[10px] opacity-75'>
                              {occurrence.subtitle}
                            </div>
                          )}
                        </>
                      );

                      const eventClassName = cn(
                        'absolute left-1 right-1 overflow-hidden rounded-md border px-2 py-1 text-left leading-tight shadow-sm outline-none transition',
                        compact ? 'text-[10px]' : 'text-xs',
                        onSelectSchedule &&
                          'cursor-pointer hover:ring-2 hover:ring-ring focus-visible:ring-2 focus-visible:ring-ring',
                        occurrence.colorClass,
                        !occurrence.isEnabled && 'opacity-45 grayscale'
                      );
                      const style = { top, minHeight: compact ? 24 : 44 };
                      const title = `${formatTime(occurrence.minuteOfDay)} - ${occurrence.title}`;

                      return onSelectSchedule ? (
                        <button
                          key={occurrence.id}
                          type='button'
                          className={eventClassName}
                          style={style}
                          title={title}
                          onClick={() =>
                            onSelectSchedule(occurrence.scheduleId)
                          }
                        >
                          {content}
                        </button>
                      ) : (
                        <div
                          key={occurrence.id}
                          className={eventClassName}
                          style={style}
                          title={title}
                        >
                          {content}
                        </div>
                      );
                    })}

                  {(overflowByDay.get(dayIndex) ?? 0) > 0 && (
                    <div className='absolute bottom-2 left-2 right-2 rounded-md border bg-background/95 px-2 py-1 text-center text-[11px] text-muted-foreground shadow-sm'>
                      {t('more', { count: overflowByDay.get(dayIndex) ?? 0 })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
