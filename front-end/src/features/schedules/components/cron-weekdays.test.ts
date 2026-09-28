import assert from 'node:assert/strict';
import test from 'node:test';

import { formatCronWeekdays, parseCronWeekdays } from './cron-weekdays.ts';

test('parses weekday lists and ranges in Monday-to-Sunday order', () => {
  assert.deepEqual(parseCronWeekdays('1,3,6,0'), [1, 3, 6, 0]);
  assert.deepEqual(parseCronWeekdays('1-5'), [1, 2, 3, 4, 5]);
  assert.deepEqual(parseCronWeekdays('7,2'), [2, 0]);
});

test('rejects unsupported weekday expressions', () => {
  assert.equal(parseCronWeekdays('*'), null);
  assert.equal(parseCronWeekdays('1-5/2'), null);
  assert.equal(parseCronWeekdays('8'), null);
  assert.equal(parseCronWeekdays(''), null);
});

test('formats weekdays in calendar order with Sunday last', () => {
  assert.equal(formatCronWeekdays([0, 6, 3, 1]), '1,3,6,0');
  assert.equal(formatCronWeekdays([1, 1, 2]), '1,2');
});
