import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildScheduleDeviceTarget,
  resolveScheduleDeviceMode
} from './schedule-device-target.ts';

test('resolveScheduleDeviceMode picks devices when serials are present', () => {
  assert.equal(
    resolveScheduleDeviceMode({
      device_group_id: 'group-1',
      device_serials: ['AAA']
    }),
    'devices'
  );
});

test('resolveScheduleDeviceMode picks group when only a group is set', () => {
  assert.equal(
    resolveScheduleDeviceMode({
      device_group_id: 'group-1',
      device_serials: []
    }),
    'group'
  );
});

test('resolveScheduleDeviceMode falls back to all', () => {
  assert.equal(resolveScheduleDeviceMode({}), 'all');
  assert.equal(resolveScheduleDeviceMode(null), 'all');
});

test('buildScheduleDeviceTarget all mode clears both targets', () => {
  assert.deepEqual(buildScheduleDeviceTarget('all', 'group-1', ['AAA']), {
    device_group_id: null,
    device_serials: []
  });
});

test('buildScheduleDeviceTarget group mode clears serials', () => {
  assert.deepEqual(buildScheduleDeviceTarget('group', 'group-1', ['AAA']), {
    device_group_id: 'group-1',
    device_serials: []
  });
});

test('buildScheduleDeviceTarget devices mode clears the group', () => {
  assert.deepEqual(
    buildScheduleDeviceTarget('devices', 'group-1', ['AAA', 'BBB']),
    { device_group_id: null, device_serials: ['AAA', 'BBB'] }
  );
});
