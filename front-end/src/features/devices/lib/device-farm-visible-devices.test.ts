import assert from 'node:assert/strict';
import test from 'node:test';

import { filterVisibleDeviceFarmDevices } from './device-farm-visible-devices.ts';
import type { Device } from '../types.ts';
import type { DeviceOut } from '../services/manage-api.ts';

function live(serial: string): Device {
  return {
    serial,
    brand: '',
    model: '',
    state: 'ONLINE',
    battery: -1
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
