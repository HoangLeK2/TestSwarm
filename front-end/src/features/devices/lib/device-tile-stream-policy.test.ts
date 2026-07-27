import assert from 'node:assert/strict';
import test from 'node:test';

import {
  resolveDeviceScreenState,
  shouldMountDeviceScreen
} from './device-tile-stream-policy';

test('active devices mount their screen by default', () => {
  assert.equal(shouldMountDeviceScreen(true, undefined), true);
});

test('an opted-in caller can pause an active device screen', () => {
  assert.equal(shouldMountDeviceScreen(true, false), false);
  assert.equal(resolveDeviceScreenState(true, false), 'paused');
});

test('inactive devices never mount their screen', () => {
  assert.equal(shouldMountDeviceScreen(false, true), false);
  assert.equal(resolveDeviceScreenState(false, true), 'inactive');
});
