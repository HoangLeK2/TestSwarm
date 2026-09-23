type TFn = (key: string, values?: Record<string, any>) => string;

function pad2(n: number) {
  return String(n).padStart(2, '0');
}

function hhmm(hour: number, minute: number) {
  return `${pad2(hour)}:${pad2(minute)}`;
}

// Labels name the real first/last run so "08:00 to 22:00" never hides a
// 22:30 run, and "every N hours" shows it is anchored to midnight, not to
// when the schedule was created.
export function cronExpressionToHumanReadable(
  cronExpression: string,
  t?: TFn
): string {
  const parts = cronExpression.trim().split(/\s+/);
  if (parts.length !== 5) return cronExpression;

  const [minField, hourField, domField, monField, dowField] = parts;
  if (domField !== '*' || monField !== '*' || dowField !== '*') {
    return cronExpression;
  }

  const tr = (key: string, fallback: string, values?: Record<string, any>) =>
    t ? t(key, values) : fallback;

  const everyMin = minField.match(/^\*\/(\d+)$/);
  if (everyMin && hourField === '*') {
    const interval = Number(everyMin[1]);
    const times = [0, interval, interval * 2]
      .filter((minute) => minute < 60)
      .map(pad2)
      .join(', ');
    return tr(
      'everyMinutes',
      `Every ${interval} minutes, restarting at minute 00 each hour (minutes ${times}, …)`,
      { interval, times }
    );
  }

  const everyHour = hourField.match(/^\*\/(\d+)$/);
  if (everyHour) {
    const interval = Number(everyHour[1]);
    const minute = Number(minField);
    const times = [0, interval, interval * 2]
      .filter((hour) => hour < 24)
      .map((hour) => hhmm(hour, minute))
      .join(', ');
    return tr(
      'everyHoursAtMinute',
      `Every ${interval} hours, counted from midnight (${times}, …)`,
      { interval, times }
    );
  }

  if (!minField.includes('/') && !hourField.includes('/')) {
    const minute = Number(minField);
    const hour = Number(hourField);
    if (Number.isFinite(minute) && Number.isFinite(hour)) {
      return tr('dailyAt', `Every day at ${pad2(hour)}:${pad2(minute)}`, {
        hour: pad2(hour),
        minute: pad2(minute)
      });
    }
  }

  const hourRange = hourField.match(/^(\d{1,2})-(\d{1,2})$/);
  if (everyMin && hourRange) {
    const interval = Number(everyMin[1]);
    const start = hhmm(Number(hourRange[1]), 0);
    const end = hhmm(
      Number(hourRange[2]),
      Math.floor(59 / interval) * interval
    );
    return tr(
      'windowMinutes',
      `Every ${interval} minutes from ${start} to ${end}`,
      { interval, start, end }
    );
  }

  const minute = Number(minField);
  if (!Number.isFinite(minute)) return cronExpression;

  const hourStep = hourField.match(/^(\d{1,2})-(\d{1,2})\/(\d+)$/);
  if (hourStep) {
    const startHour = Number(hourStep[1]);
    const endHour = Number(hourStep[2]);
    const step = Number(hourStep[3]);
    const lastHour =
      endHour >= startHour
        ? startHour + Math.floor((endHour - startHour) / step) * step
        : endHour;
    const start = hhmm(startHour, minute);
    const end = hhmm(lastHour, minute);
    return tr(
      'windowHoursStep',
      `Every ${step} hours from ${start} to ${end}`,
      { step, start, end }
    );
  }

  if (hourRange) {
    const start = hhmm(Number(hourRange[1]), minute);
    const end = hhmm(Number(hourRange[2]), minute);
    return tr('windowHoursRangeOnly', `Every hour from ${start} to ${end}`, {
      start,
      end
    });
  }

  return cronExpression;
}
