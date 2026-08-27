import assert from 'node:assert/strict';
import test from 'node:test';

import { mergeDeviceFarmWsStatus } from './device-farm-ws-status.ts';
import type { Device, WsMessage } from '../types.ts';

function device(serial: string, opts: Partial<Device> = {}): Device {
  return {
    serial,
    brand: '',
    model: '',
    state: 'READY',
    battery: -1,
    agent_connected: true,
    ...opts
  };
}

function status(
  serial: string,
  opts: Partial<Extract<WsMessage, { type: 'status' }>> = {}
): Extract<WsMessage, { type: 'status' }> {
  return {
    type: 'status',
    serial,
    state: 'READY',
    ...opts
  };
}

test('dashboard mode does not seed devices from websocket status before snapshot lands', () => {
  const result = mergeDeviceFarmWsStatus([], status('10AE7S00HD002JK'), {
    liveSnapshotAuthoritative: true
  });

  assert.deepEqual(result, []);
});

test('dashboard mode ignores stale offline websocket status', () => {
  const previous = [device('10AE7S00HD002JK')];

  const result = mergeDeviceFarmWsStatus(
    previous,
    status('10AE7S00HD002JK', {
      state: 'DEAD',
      agent_connected: false,
      u2_ready: true,
      touch_method: 'u2'
    }),
    { liveSnapshotAuthoritative: true }
  );

  assert.deepEqual(result, previous);
});

test('default mode still applies websocket offline status', () => {
  const result = mergeDeviceFarmWsStatus(
    [device('10AE7S00HD002JK')],
    status('10AE7S00HD002JK', {
      state: 'DEAD',
      agent_connected: false
    })
  );

  assert.equal(result[0]?.state, 'DEAD');
  assert.equal(result[0]?.agent_connected, false);
});

test('dashboard mode updates live websocket status for devices in snapshot', () => {
  const result = mergeDeviceFarmWsStatus(
    [device('10AE7S00HD002JK')],
    status('10AE7S00HD002JK', {
      state: 'READY',
      agent_connected: true,
      battery: 88
    }),
    { liveSnapshotAuthoritative: true }
  );

  assert.equal(result.length, 1);
  assert.equal(result[0]?.serial, '10AE7S00HD002JK');
  assert.equal(result[0]?.battery, 88);
});

test('websocket status without dimensions does not invent fallback screen size', () => {
  const result = mergeDeviceFarmWsStatus(
    [],
    status('emulator-5560', {
      agent_connected: true,
      model: 'galaxy_note10_plus'
    })
  );

  assert.equal(result[0]?.screen_width, undefined);
  assert.equal(result[0]?.screen_height, undefined);
});

test('websocket status without dimensions preserves API screen size', () => {
  const result = mergeDeviceFarmWsStatus(
    [
      device('emulator-5560', {
        screen_width: 1440,
        screen_height: 3040
      })
    ],
    status('emulator-5560', {
      agent_connected: true
    })
  );

  assert.equal(result[0]?.screen_width, 1440);
  assert.equal(result[0]?.screen_height, 3040);
});
