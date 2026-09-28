import assert from 'node:assert/strict';
import test from 'node:test';

import { cronExpressionToHumanReadable as describe } from './cron-describe.ts';

test('every N hours shows it counts from midnight', () => {
  assert.equal(
    describe('0 */2 * * *'),
    'Every 2 hours, counted from midnight (00:00, 02:00, 04:00, …)'
  );
  assert.equal(
    describe('30 */5 * * *'),
    'Every 5 hours, counted from midnight (00:30, 05:30, 10:30, …)'
  );
});

test('minute window ends at the real last run, not HH:00', () => {
  assert.equal(
    describe('*/30 8-22 * * *'),
    'Every 30 minutes from 08:00 to 22:30'
  );
  assert.equal(
    describe('*/20 9-11 * * *'),
    'Every 20 minutes from 09:00 to 11:40'
  );
});

test('hour-step window ends at the last reachable hour', () => {
  assert.equal(
    describe('15 8-22/3 * * *'),
    'Every 3 hours from 08:15 to 20:15'
  );
  assert.equal(describe('0 9-17 * * *'), 'Every hour from 09:00 to 17:00');
});

test('every N minutes shows it restarts at minute 00 each hour', () => {
  assert.equal(
    describe('*/15 * * * *'),
    'Every 15 minutes, restarting at minute 00 each hour (minutes 00, 15, 30, …)'
  );
  assert.equal(
    describe('*/45 * * * *'),
    'Every 45 minutes, restarting at minute 00 each hour (minutes 00, 45, …)'
  );
});

test('selected weekdays are described in calendar order', () => {
  assert.equal(
    describe('15 8 * * 1,3,6,0'),
    'Every Mon, Wed, Sat, Sun at 08:15'
  );
  assert.equal(
    describe('0 9 * * 1-5'),
    'Every Mon, Tue, Wed, Thu, Fri at 09:00'
  );
});
