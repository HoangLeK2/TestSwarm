import assert from 'node:assert/strict';
import test from 'node:test';

import { isControlRecordConnectedDevice } from '../lib/control-record-device-state.ts';

test('control record treats runtime and FSM online states as connected', () => {
  for (const state of ['READY', 'DeviceState.READY', 'ONLINE', 'BUSY']) {
    assert.equal(isControlRecordConnectedDevice({ state }), true, state);
  }
});

test('control record excludes offline terminal states', () => {
  for (const state of [
    'CONNECTING',
    'RECONNECTING',
    'DEAD',
    'DISCONNECTED',
    'ERROR',
    'UNKNOWN',
    ''
  ]) {
    assert.equal(isControlRecordConnectedDevice({ state }), false, state);
  }
});
