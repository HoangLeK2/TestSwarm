import assert from 'node:assert/strict';
import test from 'node:test';

import {
  deviceSerialMatches,
  isControlRecordConnectedDevice,
  isManualControlBlockedByAutomation,
  isManualControlEligible,
  resolveControlRecordConnectedDevices,
  resolveControlRecordHierarchySerial,
  resolveControlRecordSelectedDevice,
  shouldShowControlRecordNoDeviceBanner
} from './control-record-device-state.ts';

test('deviceSerialMatches accepts exact and suffix serial aliases', () => {
  assert.equal(deviceSerialMatches('10AE7S00HD002JK', 'HD002JK'), true);
  assert.equal(deviceSerialMatches('phone-A', 'PHONE-A'), true);
  assert.equal(deviceSerialMatches('', 'PHONE-A'), false);
  assert.equal(deviceSerialMatches('phone-A', 'phone-B'), false);
});

test('isManualControlEligible allows READY idle devices and manual takeover', () => {
  assert.equal(
    isManualControlEligible({ state: 'DeviceState.READY', scenario_active: 0 }),
    true
  );
  assert.equal(
    isManualControlEligible({ state: 'READY', scenario_active: 1 }),
    false
  );
  assert.equal(
    isManualControlEligible({
      state: 'READY',
      scenario_active: 1,
      manual_takeover_active: true
    }),
    true
  );
  assert.equal(isManualControlEligible({ state: 'BUSY' }), false);
});

test('isManualControlBlockedByAutomation keeps takeover devices unblocked', () => {
  assert.equal(
    isManualControlBlockedByAutomation({
      state: 'BUSY',
      scenario_active: 1
    }),
    true
  );
  assert.equal(
    isManualControlBlockedByAutomation({
      state: 'BUSY',
      scenario_active: 1,
      manual_takeover_active: true
    }),
    false
  );
  assert.equal(
    isManualControlBlockedByAutomation({
      state: 'READY',
      scenario_active: 1,
      manual_takeover_active: true
    }),
    false
  );
});

test('isControlRecordConnectedDevice accepts live transport evidence while connecting', () => {
  assert.equal(
    isControlRecordConnectedDevice({ state: 'CONNECTING', u2_ready: true }),
    true
  );
  assert.equal(
    isControlRecordConnectedDevice({
      state: 'DeviceState.CONNECTING',
      touch_method: 'u2'
    }),
    true
  );
  assert.equal(
    isControlRecordConnectedDevice({
      state: 'CONNECTING',
      touch_method: 'none'
    }),
    false
  );
  assert.equal(
    isControlRecordConnectedDevice({ state: 'DISCONNECTED', u2_ready: true }),
    false
  );
  assert.equal(
    isControlRecordConnectedDevice({ state: 'DEAD', minitouch_ready: true }),
    false
  );
});

test('resolveControlRecordConnectedDevices preserves previous devices during transient empty snapshots', () => {
  const previous = [
    {
      serial: '10AE7S00HD002JK',
      state: 'READY',
      battery: 80,
      current_app: '',
      screen_width: 1260,
      screen_height: 2800
    }
  ];

  assert.deepEqual(
    resolveControlRecordConnectedDevices(
      [
        {
          serial: '10AE7S00HD002JK',
          state: 'READY',
          battery: 80,
          current_app: '',
          screen_width: 1260,
          screen_height: 2800
        }
      ],
      []
    ).map((device) => device.serial),
    ['10AE7S00HD002JK']
  );
  assert.deepEqual(
    resolveControlRecordConnectedDevices([], previous).map(
      (device) => device.serial
    ),
    ['10AE7S00HD002JK']
  );
  assert.deepEqual(
    resolveControlRecordConnectedDevices(
      [
        {
          serial: '10AE7S00HD002JK',
          state: 'CONNECTING',
          battery: 80,
          current_app: '',
          screen_width: 1260,
          screen_height: 2800,
          touch_method: 'none',
          u2_ready: false
        }
      ],
      previous
    ).map((device) => device.serial),
    ['10AE7S00HD002JK']
  );
  assert.deepEqual(
    resolveControlRecordConnectedDevices(
      [
        {
          serial: '10AE7S00HD002JK',
          state: 'DEAD',
          battery: 0,
          current_app: '',
          screen_width: 1260,
          screen_height: 2800
        }
      ],
      previous
    ),
    []
  );
});

test('resolveControlRecordConnectedDevices preserves a selected-capable device during a partial disconnect snapshot', () => {
  const previous = [
    {
      serial: 'target',
      brand: '',
      model: '',
      state: 'READY',
      battery: 80,
      current_app: '',
      screen_width: 1080,
      screen_height: 1920
    },
    {
      serial: 'fallback',
      brand: '',
      model: '',
      state: 'READY',
      battery: 80,
      current_app: '',
      screen_width: 1080,
      screen_height: 1920
    }
  ];

  const resolved = resolveControlRecordConnectedDevices(
    [
      {
        ...previous[0],
        state: 'DISCONNECTED',
        touch_method: 'none',
        u2_ready: false
      },
      previous[1]
    ],
    previous
  );

  assert.deepEqual(
    resolved.map((device) => device.serial),
    ['target', 'fallback']
  );
  assert.equal(resolved[0].state, 'READY');
});

test('resolveControlRecordConnectedDevices can grace a selected device through a terminal snapshot', () => {
  const previous = [
    {
      serial: 'target',
      brand: '',
      model: '',
      state: 'READY',
      battery: 80,
      current_app: '',
      screen_width: 1080,
      screen_height: 1920
    }
  ];

  const resolved = resolveControlRecordConnectedDevices(
    [{ ...previous[0], state: 'DEAD' }],
    previous,
    { preserveTerminalSerials: new Set(['target']) }
  );

  assert.equal(resolved[0], previous[0]);
});

test('resolveControlRecordHierarchySerial keeps the user-selected serial stable during device snapshot gaps', () => {
  assert.equal(
    resolveControlRecordHierarchySerial('10AE7S00HD002JK', null),
    '10AE7S00HD002JK'
  );
  assert.equal(
    resolveControlRecordHierarchySerial(' 10AE7S00HD002JK ', 'other'),
    '10AE7S00HD002JK'
  );
  assert.equal(
    resolveControlRecordHierarchySerial(null, '10AE7S00HD002JK'),
    '10AE7S00HD002JK'
  );
  assert.equal(resolveControlRecordHierarchySerial('', ''), null);
});

test('resolveControlRecordSelectedDevice never falls through to another device for an explicit serial', () => {
  const fallback = {
    serial: 'fallback',
    brand: '',
    model: '',
    state: 'READY',
    battery: 80,
    current_app: '',
    screen_width: 1080,
    screen_height: 1920
  };

  assert.equal(
    resolveControlRecordSelectedDevice([fallback], 'target'),
    null
  );
  assert.equal(
    resolveControlRecordSelectedDevice([fallback], null)?.serial,
    'fallback'
  );
});

test('shouldShowControlRecordNoDeviceBanner waits for live devices hydration', () => {
  assert.equal(
    shouldShowControlRecordNoDeviceBanner({
      devicesReady: false,
      connectedDeviceCount: 0
    }),
    false
  );
  assert.equal(
    shouldShowControlRecordNoDeviceBanner({
      devicesReady: true,
      connectedDeviceCount: 0
    }),
    true
  );
  assert.equal(
    shouldShowControlRecordNoDeviceBanner({
      devicesReady: true,
      connectedDeviceCount: 1
    }),
    false
  );
});
