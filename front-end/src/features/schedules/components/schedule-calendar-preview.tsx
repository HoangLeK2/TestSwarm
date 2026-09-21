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

type EventLayout = {
  top: number;
  minHeight: number;
  laneIndex: number;
  laneCount: number;
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
const VISUAL_EVENT_DURATION_MINUTES = 52;

const EVENT_COLORS = [
  'border-border border-l-sky-500 bg-sky-50/55 text-foreground hover:bg-sky-50 dark:border-l-sky-400 dark:bg-sky-950/25',
  'border-border border-l-emerald-500 bg-emerald-50/55 text-foreground hover:bg-emerald-50 dark:border-l-emerald-400 dark:bg-emerald-950/25',
  'border-border border-l-amber-500 bg-amber-50/55 text-foreground hover:bg-amber-50 dark:border-l-amber-400 dark:bg-amber-950/25',
  'border-border border-l-rose-500 bg-rose-50/50 text-foreground hover:bg-rose-50 dark:border-l-rose-400 dark:bg-rose-950/20',
  'border-border border-l-slate-500 bg-slate-50/70 text-foreground hover:bg-slate-100/70 dark:border-l-slate-400 dark:bg-slate-900/35'
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

function eventTop(minuteOfDay: number, hourHeight: number) {
  return ((minuteOfDay - HOURS[0] * 60) / 60) * hourHeight;
}

function buildEventLayouts(
  occurrences: Occurrence[],
  hourHeight: number,
  minHeight: number
) {
  const layouts = new Map<string, EventLayout>();
  let activeCluster: Array<Occurrence & { top: number; bottom: number }> = [];

  const flushCluster = () => {
    if (!activeCluster.length) return;

    const laneBottoms: number[] = [];
    const assigned = activeCluster.map((occurrence) => {
      const laneIndex = laneBottoms.findIndex(
        (bottom) => bottom <= occurrence.top
      );
      const nextLaneIndex = laneIndex === -1 ? laneBottoms.length : laneIndex;
      laneBottoms[nextLaneIndex] = occurrence.bottom;
      return { occurrence, laneIndex: nextLaneIndex };
    });
    const laneCount = Math.max(1, laneBottoms.length);

    assigned.forEach(({ occurrence, laneIndex }) => {
      layouts.set(occurrence.id, {
        top: occurrence.top,
        minHeight,
        laneIndex,
        laneCount
      });
    });
    activeCluster = [];
  };

  occurrences
    .map((occurrence) => {
      const top = eventTop(occurrence.minuteOfDay, hourHeight);
      return { ...occurrence, top, bottom: top + minHeight };
    })
    .sort((left, right) => {
      if (left.top !== right.top) return left.top - right.top;
      return left.title.localeCompare(right.title);
    })
    .forEach((occurrence) => {
      const clusterBottom = Math.max(
        ...activeCluster.map((item) => item.bottom),
        Number.NEGATIVE_INFINITY
      );
      if (activeCluster.length && occurrence.top >= clusterBottom) {
        flushCluster();
      }
      activeCluster.push(occurrence);
    });

  flushCluster();
  return layouts;
}

function occurrenceLaneStyle(layout: EventLayout) {
  if (layout.laneCount <= 1) {
    return {
      top: layout.top,
      height: layout.minHeight,
      minHeight: layout.minHeight,
      left: 6,
      right: 6
    };
  }

  const widthPercent = 100 / layout.laneCount;
  const leftInset = layout.laneIndex === 0 ? 6 : 1;
  const rightInset = layout.laneIndex === layout.laneCount - 1 ? 6 : 1;

  return {
    top: layout.top,
    height: layout.minHeight,
    minHeight: layout.minHeight,
    left: `calc(${widthPercent * layout.laneIndex}% + ${leftInset}px)`,
    right: `calc(${100 - widthPercent * (layout.laneIndex + 1)}% + ${rightInset}px)`
  };
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
  selectedScheduleId,
  onSelectSchedule
}: {
  schedules: ScheduleCalendarPreviewItem[];
  compact?: boolean;
  className?: string;
  selectedScheduleId?: string | null;
  onSelectSchedule?: (scheduleId: string) => void;
}) {
  const t = useTranslations('schedulesFeature.preview');
  const { occurrences, overflowByDay, unsupportedCount } =
    buildOccurrences(schedules);
  const hasItems = schedules.length > 0;
  const hourHeight = compact ? HOUR_HEIGHT : 64;
  const eventMinHeight = compact
    ? 26
    : Math.round((VISUAL_EVENT_DURATION_MINUTES / 60) * hourHeight);
  const gridHeight = HOURS.length * hourHeight;

  return (
    <section className={cn('rounded-lg border bg-background', className)}>
      <div
        className={cn(
          'flex flex-wrap items-start justify-between gap-3 border-b bg-muted/10',
          compact ? 'p-3' : 'px-4 py-3'
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
              className={cn(
                'font-semibold text-foreground',
                compact ? 'text-sm' : 'text-base'
              )}
            >
              {t('title')}
            </h3>
          </div>
          <p className='mt-1 text-xs leading-5 text-muted-foreground'>
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
            'overflow-auto bg-background',
            compact ? 'max-h-[26rem]' : 'max-h-[calc(100vh-13rem)]'
          )}
        >
          <div className={compact ? 'min-w-full' : 'min-w-[1180px]'}>
            <div
              className={cn(
                'sticky top-0 z-10 grid border-b bg-background/95 font-medium text-muted-foreground backdrop-blur',
                compact
                  ? 'grid-cols-[3.5rem_repeat(7,minmax(0,1fr))] text-[11px]'
                  : 'grid-cols-[4rem_repeat(7,minmax(9.5rem,1fr))] text-xs'
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
                  : 'grid-cols-[4rem_repeat(7,minmax(9.5rem,1fr))]'
              )}
              style={{ height: gridHeight }}
            >
              <div className='relative border-r bg-background'>
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

              {DAY_COLUMNS.map((day, dayIndex) => {
                const dayOccurrences = occurrences.filter(
                  (occurrence) => occurrence.dayIndex === dayIndex
                );
                const eventLayouts = buildEventLayouts(
                  dayOccurrences,
                  hourHeight,
                  eventMinHeight
                );

                return (
                  <div
                    key={day.key}
                    className='relative border-r bg-background last:border-r-0'
                  >
                    {HOURS.map((hour) => (
                      <div
                        key={hour}
                        className='border-b border-border/70'
                        style={{ height: hourHeight }}
                      />
                    ))}

                    {dayOccurrences.map((occurrence) => {
                      const layout = eventLayouts.get(occurrence.id);
                      if (!layout) return null;
                      if (layout.top < 0 || layout.top > gridHeight - 22) {
                        return null;
                      }

                      const content = (
                        <div className='flex min-w-0 items-center gap-1'>
                          <span className='shrink-0 font-semibold tabular-nums'>
                            {formatTime(occurrence.minuteOfDay)}
                          </span>
                          {!compact && (
                            <span className='truncate font-semibold'>
                              {occurrence.title}
                            </span>
                          )}
                          {!occurrence.isEnabled && (
                            <span className='ml-auto size-1.5 shrink-0 rounded-full bg-muted-foreground/45' />
                          )}
                        </div>
                      );

                      const eventClassName = cn(
                        'absolute overflow-hidden rounded-[3px] border border-l-4 px-2 py-1 text-left leading-tight outline-none transition-colors',
                        compact ? 'text-[10px]' : 'text-xs',
                        onSelectSchedule &&
                          'cursor-pointer hover:border-primary/30 focus-visible:ring-2 focus-visible:ring-ring',
                        selectedScheduleId === occurrence.scheduleId &&
                          'border-l-primary ring-1 ring-primary/25 ring-offset-1 ring-offset-background',
                        occurrence.colorClass,
                        !occurrence.isEnabled &&
                          'border-border border-l-muted-foreground/50 bg-muted/40 text-muted-foreground'
                      );
                      const style = occurrenceLaneStyle(layout);
                      const title = `${formatTime(occurrence.minuteOfDay)} - ${occurrence.title}${
                        occurrence.subtitle ? ` — ${occurrence.subtitle}` : ''
                      }`;

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
                      <div className='absolute bottom-2 left-2 right-2 rounded-lg border bg-background/95 px-2 py-1 text-center text-[11px] text-muted-foreground shadow-sm backdrop-blur'>
                        {t('more', { count: overflowByDay.get(dayIndex) ?? 0 })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
