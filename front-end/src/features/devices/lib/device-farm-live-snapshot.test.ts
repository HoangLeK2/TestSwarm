import assert from 'node:assert/strict';
import test from 'node:test';

import { mergeLiveDeviceSnapshot } from './device-farm-live-snapshot.ts';
import type { Device } from '../types.ts';

function device(serial: string, state = 'READY'): Device {
  return {
    serial,
    brand: '',
    model: '',
    state,
    battery: -1
  };
}

test('mergeLiveDeviceSnapshot keeps live devices across an empty transient snapshot', () => {
  const result = mergeLiveDeviceSnapshot([device('relay-1')], []);

  assert.deepEqual(
    result.map((item) => item.serial),
    ['relay-1']
  );
});

test('mergeLiveDeviceSnapshot drops devices with explicit offline evidence', () => {
  const result = mergeLiveDeviceSnapshot([device('relay-1', 'DISCONNECTED')], []);

  assert.deepEqual(result, []);
});

test('mergeLiveDeviceSnapshot merges runtime serial changes through registered serial', () => {
  const result = mergeLiveDeviceSnapshot(
    [{ ...device('10.0.0.2:5555'), registered_serial: 'HW123' }],
    [{ ...device('10.0.0.9:41111'), registered_serial: 'HW123' }]
  );

  assert.equal(result.length, 1);
  assert.equal(result[0].serial, '10.0.0.9:41111');
  assert.equal(result[0].registered_serial, 'HW123');
});
