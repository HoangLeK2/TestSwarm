import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getDeviceGridColumnCount,
  getDeviceGridRowBounds,
  getDeviceGridRowCount
} from './device-farm-virtual-grid';

test('derives responsive columns from the existing tile width and gap', () => {
  assert.equal(getDeviceGridColumnCount(279, 10), 1);
  assert.equal(getDeviceGridColumnCount(575, 10), 1);
  assert.equal(getDeviceGridColumnCount(592, 10), 2);
  assert.equal(getDeviceGridColumnCount(1_168, 10), 3);
  assert.equal(getDeviceGridColumnCount(1_200, 10), 4);
});

test('never creates more columns than devices', () => {
  assert.equal(getDeviceGridColumnCount(1_500, 2), 2);
  assert.equal(getDeviceGridColumnCount(1_500, 0), 1);
});

test('maps virtual rows to bounded device slices', () => {
  assert.equal(getDeviceGridRowCount(10, 4), 3);
  assert.deepEqual(getDeviceGridRowBounds(0, 4, 10), {
    start: 0,
    end: 4
  });
  assert.deepEqual(getDeviceGridRowBounds(2, 4, 10), {
    start: 8,
    end: 10
  });
});
