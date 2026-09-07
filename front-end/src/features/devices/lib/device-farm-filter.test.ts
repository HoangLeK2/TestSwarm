import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ALL_RUNS,
  filterDeviceFarmDevices,
  getDeviceFarmActivity,
  listDeviceFarmRuns
} from './device-farm-filter.ts';
import type { Device } from '../types.ts';

function device(overrides: Partial<Device> & { serial: string }): Device {
  return {
    brand: 'Samsung',
    model: 'A12',
    state: 'ONLINE',
    battery: 80,
    agent_connected: true,
    ...overrides
  };
}

const idle = device({ serial: 'R58N1234', display_name: 'Máy bán hàng 1' });
const running = device({
  serial: 'R58N9999',
  brand: 'Xiaomi',
  model: 'Redmi 9',
  state: 'BUSY',
  scenario_active: 1,
  active_run: {
    execution_id: 'exec-1',
    campaign_id: 'camp-1',
    campaign_name: 'Chiến dịch A',
    scenario_id: 'scen-1',
    scenario_name: 'Kết bạn'
  }
});
const manual = device({ serial: 'MANUAL01', manual_takeover_active: true });
const offline = device({
  serial: 'OFFLINE01',
  state: 'DISCONNECTED',
  agent_connected: false
});
const fleet = [idle, running, manual, offline];

const serials = (devices: Device[]) => devices.map((d) => d.serial);
const all = { query: '', activity: 'all' as const, runKey: ALL_RUNS };

test('no filter returns the same array', () => {
  assert.equal(filterDeviceFarmDevices(fleet, { ...all, query: '  ' }), fleet);
});

test('activity buckets split idle, running, manual and unreachable', () => {
  assert.equal(getDeviceFarmActivity(idle), 'idle');
  assert.equal(getDeviceFarmActivity(running), 'running');
  assert.equal(getDeviceFarmActivity(manual), 'manual');
  assert.equal(getDeviceFarmActivity(offline), 'unavailable');
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, activity: 'idle' })),
    ['R58N1234']
  );
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, activity: 'running' })),
    ['R58N9999']
  );
});

test('a reserved session counts as manual, not idle', () => {
  assert.equal(
    getDeviceFarmActivity(device({ serial: 'X', usage_state: 'reserved' })),
    'manual'
  );
});

test('a run on a flapping agent stays visible as running', () => {
  const flapping = device({
    serial: 'FLAP',
    state: 'DISCONNECTED',
    agent_connected: false,
    scenario_active: 1
  });
  assert.equal(getDeviceFarmActivity(flapping), 'running');
});

test('health projection decides when the legacy flags disagree', () => {
  const busyByHealth = device({
    serial: 'H1',
    health: {
      overall: 'busy',
      agent: { status: 'online' },
      stream: { status: 'ready' },
      command: { status: 'busy' },
      evaluated_at: '',
      reason_codes: []
    }
  });
  const deadAgent = device({
    serial: 'H2',
    health: {
      overall: 'offline',
      agent: { status: 'offline' },
      stream: { status: 'ready' },
      command: { status: 'ready' },
      evaluated_at: '',
      reason_codes: []
    }
  });
  assert.equal(getDeviceFarmActivity(busyByHealth), 'running');
  assert.equal(getDeviceFarmActivity(deadAgent), 'unavailable');
});

test('search matches serial, display name, brand+model and the run name', () => {
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, query: '1234' })),
    ['R58N1234']
  );
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, query: 'bán hàng' })),
    ['R58N1234']
  );
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, query: 'xiaomi redmi' })),
    ['R58N9999']
  );
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, query: 'kết bạn' })),
    ['R58N9999']
  );
});

test('run filter keys on the scenario the device is executing', () => {
  assert.deepEqual(listDeviceFarmRuns(fleet), [
    { key: 'scen-1', label: 'Kết bạn', count: 1 }
  ]);
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, runKey: 'scen-1' })),
    ['R58N9999']
  );
  assert.deepEqual(
    serials(filterDeviceFarmDevices(fleet, { ...all, runKey: 'scen-missing' })),
    []
  );
});

test('filters compose', () => {
  assert.deepEqual(
    serials(
      filterDeviceFarmDevices(fleet, {
        query: 'r58n',
        activity: 'running',
        runKey: 'scen-1'
      })
    ),
    ['R58N9999']
  );
});
