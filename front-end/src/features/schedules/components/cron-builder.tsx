'use client';

import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
import { cronExpressionToHumanReadable } from './cron-describe';

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

type SimpleCronParams = {
  intervalMinutes: number;
  intervalHours: number;
  minute: number;
  hour: number;
  startHour: number;
  endHour: number;
  stepHours: number;
};

export { cronExpressionToHumanReadable } from './cron-describe';

function parseCronExpression(cronExpression: string): ParsedCron | null {
  const parts = cronExpression.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minField, hourField, domField, monField, dowField] = parts;
  if (domField !== '*' || monField !== '*' || dowField !== '*') return null;

  const everyMin = minField.match(/^\*\/(\d+)$/);
  if (everyMin && hourField === '*') {
    return { kind: 'everyMinutes', intervalMinutes: Number(everyMin[1]) };
  }

  const everyHour = hourField.match(/^\*\/(\d+)$/);
  if (everyHour && !minField.includes('/')) {
    const minute = Number(minField);
    if (!Number.isFinite(minute)) return null;
    return { kind: 'everyHours', minute, intervalHours: Number(everyHour[1]) };
  }

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
  params: SimpleCronParams
): string {
  switch (kind) {
    case 'everyMinutes':
      return `*/${params.intervalMinutes} * * * *`;
    case 'everyHours':
      return `${params.minute} */${params.intervalHours} * * *`;
    case 'dailyAt':
      return `${params.minute} ${params.hour} * * *`;
    case 'windowMinutes':
      return `*/${params.intervalMinutes} ${params.startHour}-${params.endHour} * * *`;
    case 'windowHours':
      if (params.stepHours === 1) {
        return `${params.minute} ${params.startHour}-${params.endHour} * * *`;
      }
      return `${params.minute} ${params.startHour}-${params.endHour}/${params.stepHours} * * *`;
  }
}

function applyParsedCron(parsed: ParsedCron): Partial<SimpleCronParams> & {
  kind: SimpleCronKind;
} {
  switch (parsed.kind) {
    case 'everyMinutes':
      return { kind: parsed.kind, intervalMinutes: parsed.intervalMinutes };
    case 'everyHours':
      return {
        kind: parsed.kind,
        intervalHours: parsed.intervalHours,
        minute: parsed.minute
      };
    case 'dailyAt':
      return { kind: parsed.kind, hour: parsed.hour, minute: parsed.minute };
    case 'windowMinutes':
      return {
        kind: parsed.kind,
        intervalMinutes: parsed.intervalMinutes,
        startHour: parsed.startHour,
        endHour: parsed.endHour
      };
    case 'windowHours':
      return {
        kind: parsed.kind,
        minute: parsed.minute,
        startHour: parsed.startHour,
        endHour: parsed.endHour,
        stepHours: parsed.stepHours
      };
  }
}

const DEFAULT_PARAMS: SimpleCronParams = {
  intervalMinutes: 30,
  intervalHours: 2,
  minute: 0,
  hour: 8,
  startHour: 8,
  endHour: 22,
  stepHours: 2
};

// Each preset keeps its own values: editing "every N minutes" must not
// change the window preset's interval, nor "daily at 08:59" the minute of
// "every N hours".
type ParamsByKind = Record<SimpleCronKind, SimpleCronParams>;

const DEFAULT_PARAMS_BY_KIND: ParamsByKind = {
  everyMinutes: DEFAULT_PARAMS,
  everyHours: DEFAULT_PARAMS,
  dailyAt: DEFAULT_PARAMS,
  windowMinutes: DEFAULT_PARAMS,
  windowHours: DEFAULT_PARAMS
};

function createInitialSimpleState(value: string) {
  const parsed = parseCronExpression(value);

  if (!parsed) {
    return {
      tab: 'advanced' as const,
      kind: 'everyMinutes' as SimpleCronKind,
      paramsByKind: DEFAULT_PARAMS_BY_KIND
    };
  }

  return {
    tab: 'simple' as const,
    kind: parsed.kind,
    paramsByKind: {
      ...DEFAULT_PARAMS_BY_KIND,
      [parsed.kind]: { ...DEFAULT_PARAMS, ...applyParsedCron(parsed) }
    }
  };
}

export function CronBuilder({
  value,
  onChange
}: {
  value: string;
  onChange: (cronExpression: string) => void;
}) {
  const t = useTranslations('schedulesFeature.cronBuilder');
  const initial = useMemo(() => createInitialSimpleState(value), [value]);
  const [tab, setTab] = useState<'simple' | 'advanced'>(initial.tab);
  const [kind, setKind] = useState<SimpleCronKind>(initial.kind);
  const [paramsByKind, setParamsByKind] = useState<ParamsByKind>(
    initial.paramsByKind
  );
  const params = paramsByKind[kind];
  const lastExternalValueRef = useRef(value);

  const updateParam = useCallback(
    <K extends keyof SimpleCronParams>(key: K, next: SimpleCronParams[K]) => {
      setParamsByKind((current) => {
        const merged = { ...current[kind], [key]: next };
        const cron = buildCronFromSimpleKind(kind, merged);
        lastExternalValueRef.current = cron;
        onChange(cron);
        return { ...current, [kind]: merged };
      });
    },
    [kind, onChange]
  );

  const changeKind = useCallback(
    (nextKind: SimpleCronKind) => {
      const cron = buildCronFromSimpleKind(nextKind, paramsByKind[nextKind]);
      lastExternalValueRef.current = cron;
      setKind(nextKind);
      onChange(cron);
    },
    [onChange, paramsByKind]
  );

  useLayoutEffect(() => {
    if (lastExternalValueRef.current === value) return;
    lastExternalValueRef.current = value;

    const parsed = parseCronExpression(value);
    if (!parsed) {
      setTab('advanced');
      return;
    }

    const next = applyParsedCron(parsed);
    setTab('simple');
    setKind(next.kind);
    setParamsByKind((current) => ({
      ...current,
      [next.kind]: { ...current[next.kind], ...next }
    }));
  }, [value]);

  // `*/N` restarts every hour (minutes) or every day (hours), so a
  // non-divisor N gives uneven gaps — say so instead of letting it surprise.
  const minutesHint =
    60 % params.intervalMinutes !== 0 ? (
      <p className='text-[11px] text-muted-foreground'>
        {t('intervalMinutesUneven')}
      </p>
    ) : null;
  const hoursHint =
    24 % params.intervalHours !== 0 ? (
      <p className='text-[11px] text-muted-foreground'>
        {t('intervalHoursUneven')}
      </p>
    ) : null;

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
        <TabsList className='grid w-full grid-cols-2 sm:w-auto'>
          <TabsTrigger value='simple'>{t('simple')}</TabsTrigger>
          <TabsTrigger value='advanced'>{t('advanced')}</TabsTrigger>
        </TabsList>

        <TabsContent value='simple' className='space-y-3 pt-4'>
          <div className='space-y-1'>
            <Label>{t('preset')}</Label>
            <Select
              value={kind}
              onValueChange={(v) => changeKind(v as SimpleCronKind)}
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
                max={59}
                value={params.intervalMinutes}
                onChange={(e) =>
                  updateParam(
                    'intervalMinutes',
                    Math.max(1, Math.min(59, Number(e.target.value) || 1))
                  )
                }
              />
              {minutesHint}
            </div>
          )}

          {kind === 'everyHours' && (
            <div className='grid grid-cols-1 gap-3 sm:grid-cols-2'>
              <div className='space-y-1'>
                <Label>{t('intervalHours')}</Label>
                <Input
                  type='number'
                  min={1}
                  max={23}
                  value={params.intervalHours}
                  onChange={(e) =>
                    updateParam(
                      'intervalHours',
                      Math.max(1, Math.min(23, Number(e.target.value) || 1))
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
                  value={params.minute}
                  onChange={(e) =>
                    updateParam(
                      'minute',
                      Math.max(0, Math.min(59, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
              {hoursHint && <div className='sm:col-span-2'>{hoursHint}</div>}
            </div>
          )}

          {kind === 'dailyAt' && (
            <div className='grid grid-cols-1 gap-3 sm:grid-cols-2'>
              <div className='space-y-1'>
                <Label>{t('hour0to23')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={params.hour}
                  onChange={(e) =>
                    updateParam(
                      'hour',
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
                  value={params.minute}
                  onChange={(e) =>
                    updateParam(
                      'minute',
                      Math.max(0, Math.min(59, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
            </div>
          )}

          {kind === 'windowMinutes' && (
            <div className='grid grid-cols-1 gap-3 sm:grid-cols-3'>
              <div className='space-y-1'>
                <Label>{t('intervalMinutes')}</Label>
                <Input
                  type='number'
                  min={1}
                  max={59}
                  value={params.intervalMinutes}
                  onChange={(e) =>
                    updateParam(
                      'intervalMinutes',
                      Math.max(1, Math.min(59, Number(e.target.value) || 1))
                    )
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('startHour')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={params.startHour}
                  onChange={(e) =>
                    updateParam(
                      'startHour',
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
                  value={params.endHour}
                  onChange={(e) =>
                    updateParam(
                      'endHour',
                      Math.max(0, Math.min(23, Number(e.target.value) || 0))
                    )
                  }
                />
              </div>
              {minutesHint && (
                <div className='sm:col-span-3'>{minutesHint}</div>
              )}
            </div>
          )}

          {kind === 'windowHours' && (
            <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4'>
              <div className='space-y-1'>
                <Label>{t('stepHours')}</Label>
                <Input
                  type='number'
                  min={1}
                  max={23}
                  value={params.stepHours}
                  onChange={(e) =>
                    updateParam(
                      'stepHours',
                      Math.max(1, Math.min(23, Number(e.target.value) || 1))
                    )
                  }
                />
              </div>
              <div className='space-y-1'>
                <Label>{t('startHour')}</Label>
                <Input
                  type='number'
                  min={0}
                  max={23}
                  value={params.startHour}
                  onChange={(e) =>
                    updateParam(
                      'startHour',
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
                  value={params.endHour}
                  onChange={(e) =>
                    updateParam(
                      'endHour',
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
                  value={params.minute}
                  onChange={(e) =>
                    updateParam(
                      'minute',
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
