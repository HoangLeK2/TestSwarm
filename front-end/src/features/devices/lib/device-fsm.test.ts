import assert from 'node:assert/strict';
import test from 'node:test';

import {
  deviceFsmStateOf,
  matchesDeviceFsmFilter,
  normalizeDeviceFsmState
} from './device-fsm.ts';

function device(overrides: Record<string, unknown> = {}) {
  return {
    id: 'd1',
    serial: 'SN001',
    state: 'unknown',
    ...overrides
  } as { id: string; serial: string; state: string };
}

test('normalizeDeviceFsmState defaults unknown', () => {
  assert.equal(normalizeDeviceFsmState(undefined), 'unknown');
  assert.equal(normalizeDeviceFsmState('ONLINE'), 'online');
});

test('deviceFsmStateOf treats pending serial as unknown', () => {
  assert.equal(
    deviceFsmStateOf(device({ serial: 'pending-abc', state: 'online' })),
    'unknown'
  );
});

test('matchesDeviceFsmFilter by fsm and transport', () => {
  const online = () => true;
  const d = device({ state: 'busy' }) as Parameters<
    typeof matchesDeviceFsmFilter
  >[0];
  assert.equal(matchesDeviceFsmFilter(d, 'busy', online), true);
  assert.equal(matchesDeviceFsmFilter(d, 'online', online), false);
  assert.equal(matchesDeviceFsmFilter(d, 'transport_online', online), true);
  assert.equal(matchesDeviceFsmFilter(d, 'transport_offline', online), false);
});
