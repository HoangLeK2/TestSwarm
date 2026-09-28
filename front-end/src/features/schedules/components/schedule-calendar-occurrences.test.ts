import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildOccurrences,
  eventTop,
  HOURS
} from './schedule-calendar-occurrences.ts';

const timesOnMonday = (cronExpression: string) =>
  buildOccurrences([{ id: 's', name: 'test', cronExpression }])
    .occurrences.filter((o) => o.dayIndex === 0)
    .map((o) => o.minuteOfDay / 60);

test('every 2 hours shows all 12 runs, not a sampled subset', () => {
  assert.deepEqual(
    timesOnMonday('0 */2 * * *'),
    [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]
  );
});

test('the grid covers early-morning runs', () => {
  assert.equal(HOURS[0], 0);
  assert.equal(HOURS.length, 24);
  assert.deepEqual(timesOnMonday('0 3 * * *'), [3]);
});

test('a run stays inside its own hour row, even at minute 59', () => {
  const hourHeight = 48;
  const boxHeight = 26;
  const rowTop = 8 * hourHeight;
  const rowBottom = rowTop + hourHeight;
  for (const minute of [0, 30, 59]) {
    const top = eventTop(8 * 60 + minute, hourHeight, boxHeight);
    assert.ok(
      top >= rowTop && top + boxHeight <= rowBottom,
      `08:${minute} top=${top}`
    );
  }
  assert.equal(eventTop(8 * 60, hourHeight, boxHeight), rowTop);
});

test('a weekday schedule only appears on the selected days', () => {
  const result = buildOccurrences([
    {
      id: 'weekly',
      name: 'Weekly schedule',
      cronExpression: '15 8 * * 1,3,6,0'
    }
  ]);

  assert.equal(result.unsupportedCount, 0);
  assert.deepEqual(
    result.occurrences.map(({ dayIndex, minuteOfDay }) => ({
      dayIndex,
      minuteOfDay
    })),
    [
      { dayIndex: 0, minuteOfDay: 8 * 60 + 15 },
      { dayIndex: 2, minuteOfDay: 8 * 60 + 15 },
      { dayIndex: 5, minuteOfDay: 8 * 60 + 15 },
      { dayIndex: 6, minuteOfDay: 8 * 60 + 15 }
    ]
  );
});
