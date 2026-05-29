'use client';

import { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';

type TFn = (key: string, values?: Record<string, any>) => string;

type SimpleCronKind =
  | 'everyMinutes'
  | 'everyHours'
  | 'dailyAt'
  | 'windowMinutes'
  | 'windowHours';

type ParsedCron =
  | { kind: 'everyMinutes'; intervalMinutes: number }
  | { kind: 'everyHours'; minute: number; intervalHours: number }
  | { kind: 'dailyAt'; hour: number; minute: number }
  | {
      kind: 'windowMinutes';
      intervalMinutes: number;
      startHour: number;
      endHour: number;
    }
  | {
      kind: 'windowHours';
      minute: number;
      startHour: number;
      endHour: number;
      stepHours: number;
    };

function pad2(n: number) {
  return String(n).padStart(2, '0');
}

export function cronExpressionToHumanReadable(
  cronExpression: string,
  t?: TFn
): string {
  const parts = cronExpression.trim().split(/\s+/);
  if (parts.length !== 5) return cronExpression;

  const [minField, hourField, domField, monField, dowField] = parts;

  const tr = (key: string, fallback: string, values?: Record<string, any>) =>
    t ? t(key, values) : fallback;

  // Every N minutes: */N * * * *
  const everyMin = minField.match(/^\*\/(\d+)$/);
  if (
    everyMin &&
    hourField === '*' &&
    domField === '*' &&
    monField === '*' &&
    dowField === '*'
  ) {
    return tr('everyMinutes', `Every ${Number(everyMin[1])} minutes`, {
      interval: Number(everyMin[1])
    });
  }

  // Every N hours at minute: M */N * * *
  const everyHour = hourField.match(/^\*\/(\d+)$/);
  if (everyHour && domField === '*' && monField === '*' && dowField === '*') {
    const minute = Number(minField);
    return tr(
      'everyHoursAtMinute',
      `Every ${Number(everyHour[1])} hours at ${pad2(minute)}:00`,
      {
        interval: Number(everyHour[1]),
        minute: pad2(minute)
      }
    );
  }

  if (
    !minField.includes('/') &&
    !hourField.includes('/') &&
    domField === '*' &&
    monField === '*' &&
    dowField === '*'
  ) {
    const minute = Number(minField);
    const hour = Number(hourField);
    if (Number.isFinite(minute) && Number.isFinite(hour)) {
      return tr('dailyAt', `Every day at ${pad2(hour)}:${pad2(minute)}`, {
        hour: pad2(hour),
        minute: pad2(minute)
      });
    }
  }

  // Window minutes: */N start-end * * *
  const winMin = minField.match(/^\*\/(\d+)$/);
  const winHourRange = hourField.match(/^(\d{1,2})-(\d{1,2})$/);
  if (
    winMin &&
    winHourRange &&
    domField === '*' &&
    monField === '*' &&
    dowField === '*'
  ) {
    const intervalMinutes = Number(winMin[1]);
    const startHour = Number(winHourRange[1]);
    const endHour = Number(winHourRange[2]);
    return tr(
      'windowMinutes',
      `Every ${intervalMinutes} minutes between ${pad2(startHour)}:00 and ${pad2(endHour)}:00`,
      {
        interval: intervalMinutes,
        start: pad2(startHour),
        end: pad2(endHour)
      }
    );
  }

  // Window hours with step: M start-end/step * * *
  const winHourStep = hourField.match(/^(\d{1,2})-(\d{1,2})\/(\d+)$/);
  if (winHourStep && domField === '*' && monField === '*' && dowField === '*') {
    const minute = Number(minField);
    const startHour = Number(winHourStep[1]);
    const endHour = Number(winHourStep[2]);
    const stepHours = Number(winHourStep[3]);
    return tr(
      'windowHoursStep',
      `Every ${stepHours} hours between ${pad2(startHour)}:00 and ${pad2(endHour)}:00 at ${pad2(minute)}:00`,
      {
        step: stepHours,
        start: pad2(startHour),
        end: pad2(endHour),
        minute: pad2(minute)
      }
    );
  }

  // Window hours range without step: M start-end * * *
  const winHourRangeOnly = hourField.match(/^(\d{1,2})-(\d{1,2})$/);
  if (
    winHourRangeOnly &&
    domField === '*' &&
    monField === '*' &&
    dowField === '*'
  ) {
    const minute = Number(minField);
    const startHour = Number(winHourRangeOnly[1]);
    const endHour = Number(winHourRangeOnly[2]);
    return tr(
      'windowHoursRangeOnly',
      `Every hour between ${pad2(startHour)}:00 and ${pad2(endHour)}:00 at ${pad2(minute)}:00`,
      {
        start: pad2(startHour),
        end: pad2(endHour),
        minute: pad2(minute)
      }
    );
  }

  return cronExpression;
}

function parseCronExpression(cronExpression: string): ParsedCron | null {
  const parts = cronExpression.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minField, hourField, domField, monField, dowField] = parts;
  if (domField !== '*' || monField !== '*' || dowField !== '*') return null;

  // */N * * * *
  const everyMin = minField.match(/^\*\/(\d+)$/);
  if (everyMin && hourField === '*') {
    return { kind: 'everyMinutes', intervalMinutes: Number(everyMin[1]) };
  }

  // M */N * * *
  const everyHour = hourField.match(/^\*\/(\d+)$/);
  if (everyHour && !minField.includes('/')) {
    const minute = Number(minField);
    if (!Number.isFinite(minute)) return null;
    return { kind: 'everyHours', minute, intervalHours: Number(everyHour[1]) };
  }

  // M H * * *
  if (
    !minField.includes('/') &&
    !hourField.includes('/') &&
    !hourField.includes('-') &&
    !hourField.includes('/')
  ) {
    const minute = Number(minField);
    const hour = Number(hourField);
    if (!Number.isFinite(minute) || !Number.isFinite(hour)) return null;
    return { kind: 'dailyAt', hour, minute };
  }

  // */N start-end * * *
  const winMin = minField.match(/^\*\/(\d+)$/);
  const winHourRange = hourField.match(/^(\d{1,2})-(\d{1,2})$/);
  if (winMin && winHourRange) {
    return {
      kind: 'windowMinutes',
      intervalMinutes: Number(winMin[1]),
      startHour: Number(winHourRange[1]),
      endHour: Number(winHourRange[2])
    };
  }

  // M start-end/step * * *
  const winHourStep = hourField.match(/^(\d{1,2})-(\d{1,2})\/(\d+)$/);
  if (winHourStep && !minField.includes('/')) {
    const minute = Number(minField);
    if (!Number.isFinite(minute)) return null;
    return {
      kind: 'windowHours',
      minute,
      startHour: Number(winHourStep[1]),
      endHour: Number(winHourStep[2]),
      stepHours: Number(winHourStep[3])
    };
  }

  // M start-end * * *
  const winHourRangeOnly = hourField.match(/^(\d{1,2})-(\d{1,2})$/);
  if (winHourRangeOnly && !minField.includes('/')) {
    const minute = Number(minField);
    if (!Number.isFinite(minute)) return null;
    return {
      kind: 'windowHours',
      minute,
      startHour: Number(winHourRangeOnly[1]),
      endHour: Number(winHourRangeOnly[2]),
      stepHours: 1
    };
  }

  return null;
}

function buildCronFromSimpleKind(
  kind: SimpleCronKind,
  params: Record<string, number>
): string {
  switch (kind) {
    case 'everyMinutes': {
      const intervalMinutes = params.intervalMinutes;
      return `*/${intervalMinutes} * * * *`;
    }
    case 'everyHours': {
      const minute = params.minute;
      const intervalHours = params.intervalHours;
      return `${minute} */${intervalHours} * * *`;
    }
    case 'dailyAt': {
      const hour = params.hour;
      const minute = params.minute;
      return `${minute} ${hour} * * *`;
    }
    case 'windowMinutes': {
      const intervalMinutes = params.intervalMinutes;
      const startHour = params.startHour;
      const endHour = params.endHour;
      return `*/${intervalMinutes} ${startHour}-${endHour} * * *`;
    }
    case 'windowHours': {
      const minute = params.minute;
      const startHour = params.startHour;
      const endHour = params.endHour;
      const stepHours = params.stepHours;
      if (stepHours === 1) {
        return `${minute} ${startHour}-${endHour} * * *`;
      }
      return `${minute} ${startHour}-${endHour}/${stepHours} * * *`;
    }
  }
}

export function CronBuilder({
  value,
  onChange
}: {
  value: string;
  onChange: (cronExpression: string) => void;
}) {
  const t = useTranslations('schedulesFeature.cronBuilder');
  const parsed = useMemo(() => parseCronExpression(value), [value]);
  const [tab, setTab] = useState<'simple' | 'advanced'>(
    parsed ? 'simple' : 'advanced'
  );

  const [kind, setKind] = useState<SimpleCronKind>('everyMinutes');
  const [intervalMinutes, setIntervalMinutes] = useState(30);
  const [intervalHours, setIntervalHours] = useState(2);
  const [minute, setMinute] = useState(0);
  const [hour, setHour] = useState(8);
  const [startHour, setStartHour] = useState(8);
  const [endHour, setEndHour] = useState(22);
  const [stepHours, setStepHours] = useState(2);

  // useLayoutEffect so local state matches `value` before useEffect below can call
  // onChange — otherwise the onChange effect runs with default everyMinutes (*/30…)
  // while value is e.g. "5 */2 * * *" and causes an infinite update loop with the parent.
  useLayoutEffect(() => {
    if (parsed) {
      setTab('simple');
      setKind(parsed.kind);
      if (parsed.kind === 'everyMinutes') {
        setIntervalMinutes(parsed.intervalMinutes);
      } else if (parsed.kind === 'everyHours') {
        setIntervalHours(parsed.intervalHours);
        setMinute(parsed.minute);
      } else if (parsed.kind === 'dailyAt') {
        setHour(parsed.hour);
        setMinute(parsed.minute);
      } else if (parsed.kind === 'windowMinutes') {
        setIntervalMinutes(parsed.intervalMinutes);
        setStartHour(parsed.startHour);
        setEndHour(parsed.endHour);
      } else if (parsed.kind === 'windowHours') {
        setMinute(parsed.minute);
        setStartHour(parsed.startHour);
        setEndHour(parsed.endHour);
        setStepHours(parsed.stepHours);
      }
    } else {
      setTab('advanced');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const simpleCron = useMemo(() => {
    return buildCronFromSimpleKind(kind, {
      intervalMinutes,
      intervalHours,
      minute,
      hour,
      startHour,
      endHour,
      stepHours
    });
  }, [
    kind,
    endHour,
    hour,
    intervalHours,
    intervalMinutes,
    minute,
    startHour,
    stepHours
  ]);

  useEffect(() => {
    if (tab !== 'simple') return;
    if (simpleCron && simpleCron !== value) onChange(simpleCron);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simpleCron, tab]);

  const preview = useMemo(
    () => cronExpressionToHumanReadable(value, t),
    [value, t]
  );

  return (
    <div className='space-y-2'>
      <div className='space-y-1'>
        <Label>{t('cronScheduleLabel')}</Label>
        <div className='rounded-md border bg-muted/30 px-3 py-2 text-sm font-medium'>
          {preview}
          {preview !== value && (
            <span className='ml-2 font-mono text-[11px] text-muted-foreground'>
              ({value})
            </span>
          )}
        </div>
      </div>

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as 'simple' | 'advanced')}
      >
        <TabsList>
          <TabsTrigger value='simple'>{t('simple')}</TabsTrigger>
          <TabsTrigger value='advanced'>{t('advanced')}</TabsTrigger>
        </TabsList>

        <TabsContent value='simple' className='space-y-3 pt-4'>
          <div className='space-y-1'>
            <Label>{t('preset')}</Label>
            <Select
              value={kind}
              onValueChange={(v) => setKind(v as SimpleCronKind)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent className='z-[10001]'>
                <SelectItem value='everyMinutes'>
                  {t('presetEveryMinutes')}
                </SelectItem>
                <SelectItem value='everyHours'>
                  {t('presetEveryHours')}
                </SelectItem>
                <SelectItem value='dailyAt'>{t('presetDailyAt')}</SelectItem>
                <SelectItem value='windowMinutes'>
                  {t('presetWindowMinutes')}
                </SelectItem>
                <SelectItem value='windowHours'>
                  {t('presetWindowHours')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {kind === 'everyMinutes' && (
            <div className='space-y-1'>
              <Label>{t('intervalMinutes')}</Label>
              <Input
                type='number'
                min={1}
                value={intervalMinutes}
                onChange={(e) =>
                  setIntervalMinutes(Math.max(1, Number(e.target.value) || 1))
                }
              />
            </div>
          )}

          {kind === 'everyHours' && (
            <div className='grid grid-cols-2 gap-3'>
              <div className='space-y-1'>
                <Label>{t('intervalHours')}</Label>
                <Input
                  type='number'
                  min={1}
                  value={intervalHours}
                  onChange={(e) =>
                    setIntervalHours(Math.max(1, Number(e.target.value) || 1))
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('minute0to59')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={59}
                  value={minute}
                  onChange={(e) =>
                    setMinute(
                      Math.max(0, Math.min(59, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
            </div>
          )}

          {kind === 'dailyAt' && (
            <div className='grid grid-cols-2 gap-3'>
              <div className='space-y-1'>
                <Label>{t('hour0to23')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={hour}
                  onChange={(e) =>
                    setHour(
                      Math.max(0, Math.min(23, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('minute0to59')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={59}
                  value={minute}
                  onChange={(e) =>
                    setMinute(
                      Math.max(0, Math.min(59, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
            </div>
          )}

          {kind === 'windowMinutes' && (
            <div className='grid grid-cols-3 gap-3'>
              <div className='space-y-1'>
                <Label>{t('intervalMinutes')}</Label>
                <Input
                  type='number'
                  min={1}
                  value={intervalMinutes}
                  onChange={(e) =>
                    setIntervalMinutes(Math.max(1, Number(e.target.value) || 1))
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('startHour')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={startHour}
                  onChange={(e) =>
                    setStartHour(
                      Math.max(0, Math.min(23, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('endHour')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={endHour}
                  onChange={(e) =>
                    setEndHour(
                      Math.max(0, Math.min(23, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
            </div>
          )}

          {kind === 'windowHours' && (
            <div className='grid grid-cols-4 gap-3'>
              <div className='space-y-1'>
                <Label>{t('stepHours')}</Label>
                <Input
                  type='number'
                  min={1}
                  value={stepHours}
                  onChange={(e) =>
                    setStepHours(Math.max(1, Number(e.target.value) || 1))
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('startHour')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={startHour}
                  onChange={(e) =>
                    setStartHour(
                      Math.max(0, Math.min(23, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('endHour')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={endHour}
                  onChange={(e) =>
                    setEndHour(
                      Math.max(0, Math.min(23, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('minute')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={59}
                  value={minute}
                  onChange={(e) =>
                    setMinute(
                      Math.max(0, Math.min(59, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value='advanced' className='space-y-2 pt-4'>
          <div className='space-y-1'>
            <Label>{t('rawCronExpression')}</Label>
            <Input
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder={t('rawCronPlaceholder')}
            />
            <p className='text-[11px] text-muted-foreground'>
              {t('rawCronHelp')}
            </p>
          </div>
          <div className='rounded border bg-muted/10 p-2 text-[11px] text-muted-foreground'>
            {preview}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
