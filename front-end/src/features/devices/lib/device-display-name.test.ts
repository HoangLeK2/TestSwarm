import assert from 'node:assert/strict';
import test from 'node:test';

import {
  deviceDisplayName,
  deviceSecondarySerial,
  shortDeviceSerial
} from './device-display-name.ts';

test('deviceDisplayName prefers user alias over model and serial', () => {
  const device = {
    serial: 'ZY22H7ABCDEF',
    name: 'PT-01',
    brand: 'samsung',
    model: 'SM-N975F'
  };

  assert.equal(deviceDisplayName(device), 'PT-01');
  assert.equal(deviceSecondarySerial(device), 'ZY22H7ABCDEF');
});

test('deviceDisplayName falls back to model when alias is empty', () => {
  assert.equal(
    deviceDisplayName({
      serial: 'ZY22H7ABCDEF',
      name: '  ',
      brand: 'samsung',
      model: 'SM-N975F'
    }),
    'samsung SM-N975F'
  );
});

test('shortDeviceSerial keeps tail stable for dense phone grids', () => {
  assert.equal(shortDeviceSerial('ZY22H7ABCDEFGHIJKLMNOP'), '…IJKLMNOP');
  assert.equal(shortDeviceSerial('SM-N975F'), 'SM-N975F');
});
