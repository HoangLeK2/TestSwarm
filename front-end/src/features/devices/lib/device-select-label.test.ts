import assert from 'node:assert/strict';
import test from 'node:test';

import {
  deviceSelectFullTitle,
  formatDeviceSelectLabel
} from './device-select-label.ts';

test('device select labels prefer the configured device name', () => {
  const device = {
    name: 'Máy Vivo mới',
    display_name: 'Tên hiển thị cũ',
    brand: 'vivo',
    model: 'V2352A',
    serial: '10AE7S00HD002JK'
  };

  assert.equal(
    formatDeviceSelectLabel(device),
    'Máy Vivo mới — 10AE7S00HD002JK'
  );
  assert.equal(
    deviceSelectFullTitle(device),
    'Máy Vivo mới — 10AE7S00HD002JK'
  );
});

test('device select labels fall back to display name before model', () => {
  const device = {
    display_name: 'Máy dự phòng',
    brand: 'vivo',
    model: 'V2352A',
    serial: '10AE7S00HD002JK'
  };

  assert.equal(
    formatDeviceSelectLabel(device),
    'Máy dự phòng — 10AE7S00HD002JK'
  );
});
