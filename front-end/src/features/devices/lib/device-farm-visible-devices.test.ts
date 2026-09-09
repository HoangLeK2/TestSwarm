import assert from 'node:assert/strict';
import test from 'node:test';

import {
  filterDeviceFarmActiveGridDevices,
  filterVisibleDeviceFarmDevices,
  isVisibleDeviceFarmActiveDevice
} from './device-farm-visible-devices.ts';
import type { Device } from '../types.ts';
import type { DeviceOut } from '../services/manage-api.ts';

function live(serial: string): Device {
  return {
    serial,
    brand: '',
    model: '',
    state: 'ONLINE',
    battery: -1,
    agent_connected: true
  };
}

function registered(serial: string, opts: Partial<DeviceOut> = {}): DeviceOut {
  return {
    id: serial,
    serial,
    name: serial,
    device_key: '',
    user_id: null,
    brand: '',
    model: '',
    android_version: '',
    sdk_version: 0,
    screen_width: 1080,
    screen_height: 1920,
    last_seen: null,
    created_at: '',
    adb_serial: null,
    adb_ip: null,
    adb_port: 5555,
    state: 'online',
    ...opts
  };
}

test('default device farm filter keeps registered live devices only', () => {
  const result = filterVisibleDeviceFarmDevices(
    [live('registered-1'), live('unregistered-1')],
    [registered('registered-1')]
  );

  assert.deepEqual(
    result.map((device) => device.serial),
    ['registered-1']
  );
});

test('device farm filter matches alias runtime serial through registered serial', () => {
  const result = filterVisibleDeviceFarmDevices(
    [
      {
        ...live('10.0.0.2:5555'),
        registered_serial: 'registered-1'
      }
    ],
    [registered('registered-1', { adb_serial: '10.0.0.2:5555' })]
  );

  assert.deepEqual(
    result.map((device) => device.serial),
    ['10.0.0.2:5555']
  );
});

test('device farm filter keeps relay-managed devices visible while live route owns liveness', () => {
  const result = filterVisibleDeviceFarmDevices(
    [live('relay-1')],
    [registered('relay-1', { adb_serial: 'relay-1' })]
  );

  assert.deepEqual(
    result.map((device) => device.serial),
    ['relay-1']
  );
});

test('device farm filter trusts live route while registered devices are hydrating', () => {
  const result = filterVisibleDeviceFarmDevices([live('relay-1')], []);

  assert.deepEqual(
    result.map((device) => device.serial),
    ['relay-1']
  );
});

test('dashboard active check keeps transport-live devices visible despite stale offline state', () => {
  assert.equal(
    isVisibleDeviceFarmActiveDevice({
      ...live('relay-1'),
      state: 'DISCONNECTED',
      stf_connected: true
    } as Device),
    true
  );
  assert.equal(
    isVisibleDeviceFarmActiveDevice({
      ...live('agent-1'),
      state: 'DISCONNECTED',
      agent_connected: true,
      u2_ready: true,
      touch_method: 'u2'
    } as Device),
    true
  );
});

test('dashboard active check keeps campaign-running devices visible despite stale offline state', () => {
  assert.equal(
    isVisibleDeviceFarmActiveDevice({
      ...live('campaign-1'),
      state: 'DISCONNECTED',
      agent_connected: false,
      stf_connected: false,
      u2_ready: false,
      minitouch_ready: false,
      touch_method: 'none',
      scenario_active: 1
    }),
    true
  );
});

test('dashboard active check keeps reserved work devices visible despite stale offline state', () => {
  assert.equal(
    isVisibleDeviceFarmActiveDevice({
      ...live('reserved-1'),
      state: 'DISCONNECTED',
      agent_connected: false,
      stf_connected: false,
      u2_ready: false,
      minitouch_ready: false,
      touch_method: 'none',
      usage_state: 'reserved'
    } as Device),
    true
  );
});

test('dashboard active check drops disconnected devices with only stale readiness flags', () => {
  assert.equal(
    isVisibleDeviceFarmActiveDevice({
      ...live('10AE7S00HD002JK'),
      state: 'DISCONNECTED',
      agent_connected: false,
      u2_ready: true,
      touch_method: 'none',
      stf_connected: false
    }),
    false
  );
});

test('dashboard active check drops disconnected devices with stale touch method', () => {
  assert.equal(
    isVisibleDeviceFarmActiveDevice({
      ...live('10AE7S00HD002JK'),
      state: 'DISCONNECTED',
      agent_connected: false,
      u2_ready: true,
      touch_method: 'u2',
      stf_connected: false
    }),
    false
  );
});

test('dashboard active check drops explicit offline devices without live transport evidence', () => {
  assert.equal(
    isVisibleDeviceFarmActiveDevice({
      ...live('offline-1'),
      state: 'DeviceState.DISCONNECTED',
      agent_connected: false,
      touch_method: 'none',
      u2_ready: false,
      minitouch_ready: false
    }),
    false
  );
});

test('device farm active grid drops dead phones even with stale media-plane flags', () => {
  const devices = [
    live('active-1'),
    {
      ...live('10AE7S00HD002JK'),
      state: 'DEAD',
      agent_connected: false,
      stf_connected: false,
      media_adapter_connected: true,
      media_stream_active: true,
      media_stream_connected: true
    }
  ];

  assert.deepEqual(
    filterDeviceFarmActiveGridDevices(devices).map((device) => device.serial),
    ['active-1']
  );
});

test('device farm active grid drops media-only phones without command channel', () => {
  const devices = [
    live('active-1'),
    {
      ...live('10AE7S00HD002JK'),
      state: 'MEDIA_READY',
      agent_connected: false,
      stf_connected: false,
      u2_ready: false,
      minitouch_ready: false,
      touch_method: 'none',
      media_adapter_connected: true,
      media_stream_active: true,
      media_stream_connected: true,
      health: {
        overall: 'offline',
        agent: { status: 'offline' },
        stream: { status: 'starting' },
        command: { status: 'unavailable' },
        evaluated_at: '',
        reason_codes: []
      }
    }
  ];

  assert.deepEqual(
    filterDeviceFarmActiveGridDevices(devices).map((device) => device.serial),
    ['active-1']
  );
});
