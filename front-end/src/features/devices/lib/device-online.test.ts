import assert from 'node:assert/strict';
import test from 'node:test';

import {
  computeDeviceTransportCounts,
  isDeviceOnlineForList,
  resolveDeviceRelay
} from './device-online.ts';
import type { DeviceOut, RelayAgentOut } from '../services/manage-api.ts';

function device(overrides: Partial<DeviceOut> = {}): DeviceOut {
  return {
    id: 'd1',
    serial: 'SN001',
    name: 'Phone A',
    device_key: 'key',
    user_id: 'u1',
    brand: 'Google',
    model: 'Pixel',
    android_version: '14',
    sdk_version: 34,
    screen_width: 1080,
    screen_height: 2400,
    last_seen: null,
    created_at: '2026-01-01T00:00:00Z',
    adb_serial: null,
    adb_ip: null,
    adb_port: 5555,
    state: 'unknown',
    ...overrides
  };
}

function relay(overrides: Partial<RelayAgentOut> = {}): RelayAgentOut {
  return {
    relay_id: 'relay-1',
    hostname: 'host-a',
    ip: '10.0.0.1',
    version: '1',
    serials: [],
    status: 'offline',
    connected_at: '2026-01-01T00:00:00Z',
    last_heartbeat_at: null,
    disconnected_at: null,
    ...overrides
  };
}

test('resolveDeviceRelay prefers relay_id then serial aliases', () => {
  const r = relay({ relay_id: 'r1', serials: ['adb-1'] });
  const map: Record<string, RelayAgentOut> = {
    r1: r,
    'adb-1': r
  };
  assert.equal(
    resolveDeviceRelay(device({ relay_id: 'r1', serial: 'SN' }), map)?.relay_id,
    'r1'
  );
  assert.equal(
    resolveDeviceRelay(device({ serial: 'adb-1' }), map)?.relay_id,
    'r1'
  );
});

test('isDeviceOnlineForList is false for pending devices', () => {
  const now = Date.parse('2026-05-29T12:00:00Z');
  assert.equal(
    isDeviceOnlineForList(
      device({ serial: 'pending-abc', last_seen: '2026-05-29T11:59:30Z' }),
      {},
      now
    ),
    false
  );
});

test('isDeviceOnlineForList is true when relay transport is connected', () => {
  const now = Date.now();
  const r = relay({
    status: 'online',
    live_connected: true,
    serials: ['SN001'],
    connected_at: new Date(now - 120_000).toISOString(),
    last_heartbeat_at: new Date(now - 5_000).toISOString()
  });
  const map = { SN001: r };
  assert.equal(
    isDeviceOnlineForList(
      device({ last_seen: new Date(now - 7_200_000).toISOString() }),
      map,
      now
    ),
    true
  );
});

test('isDeviceOnlineForList is false for relay-managed device without live agent-boot', () => {
  const now = Date.now();
  const r = relay({
    status: 'offline',
    live_connected: false,
    serials: ['SN001'],
    connected_at: new Date(now - 120_000).toISOString(),
    last_heartbeat_at: new Date(now - 5_000).toISOString()
  });
  const map = { SN001: r };
  assert.equal(
    isDeviceOnlineForList(
      device({
        serial: 'SN001',
        adb_serial: 'SN001',
        last_seen: new Date(now - 1_000).toISOString()
      }),
      map,
      now
    ),
    false
  );
});

test('isDeviceOnlineForList is false when relay is only connecting', () => {
  const now = Date.now();
  const r = relay({
    status: 'online',
    serials: ['SN001'],
    connected_at: new Date(now - 5_000).toISOString(),
    last_heartbeat_at: new Date(now - 5_000).toISOString()
  });
  const map = { SN001: r };
  assert.equal(
    isDeviceOnlineForList(
      device({ last_seen: new Date(now - 7_200_000).toISOString() }),
      map,
      now
    ),
    false
  );
});

test('isDeviceOnlineForList uses last_seen within 60s when relay offline', () => {
  const now = Date.parse('2026-05-29T12:00:00Z');
  assert.equal(
    isDeviceOnlineForList(
      device({ last_seen: '2026-05-29T11:59:30Z' }),
      {},
      now
    ),
    true
  );
  assert.equal(
    isDeviceOnlineForList(
      device({ last_seen: '2026-05-29T11:58:00Z' }),
      {},
      now
    ),
    false
  );
});

test('isDeviceOnlineForList is false without relay and last_seen', () => {
  const now = Date.parse('2026-05-29T12:00:00Z');
  assert.equal(isDeviceOnlineForList(device(), {}, now), false);
});

test('computeDeviceTransportCounts matches isDeviceOnlineForList per device', () => {
  const now = Date.parse('2026-05-29T12:00:00Z');
  const r = relay({
    status: 'online',
    live_connected: true,
    serials: ['SN001']
  });
  const map = { SN001: r };
  const devices = [
    device({ serial: 'SN001', last_seen: '2026-05-29T11:58:00Z' }),
    device({ id: 'd2', serial: 'SN002', last_seen: '2026-05-29T11:59:30Z' })
  ];
  const counts = computeDeviceTransportCounts(devices, map, now);
  assert.equal(counts.total, 2);
  assert.equal(counts.online, 2);
  assert.equal(counts.offline, 0);
});
