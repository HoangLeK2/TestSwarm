import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { DeviceOut, FleetStatsOut } from '../services/manage-api.ts';
import {
  applyLifecycleEventToDevices,
  applyLifecycleEventToFleetStats,
  applySnapshotToDevices,
  snapshotDeviceIdsMatchCache
} from './lifecycle-cache.ts';

function device(id: string, state: string): DeviceOut {
  return {
    id,
    serial: `serial-${id}`,
    name: id,
    device_key: 'k',
    user_id: null,
    brand: 'b',
    model: 'm',
    android_version: '14',
    sdk_version: 34,
    screen_width: 1080,
    screen_height: 2400,
    last_seen: null,
    created_at: '2026-01-01T00:00:00Z',
    adb_serial: null,
    adb_ip: null,
    adb_port: 5555,
    state
  };
}

function fleetStats(
  devices: FleetStatsOut['devices'],
  sessions: FleetStatsOut['active_sessions'] = {
    user: 0,
    execution: 0,
    campaign: 0,
    system: 0,
    unknown: 0,
    total: 0
  }
): FleetStatsOut {
  return {
    filters: { organization_id: 'org-1', group_id: null, relay_host: null },
    devices,
    active_sessions: sessions,
    owner_anomalies: null
  };
}

describe('lifecycle-cache', () => {
  it('snapshotDeviceIdsMatchCache detects added or removed devices', () => {
    const cached = [device('dev-1', 'online'), device('dev-2', 'online')];
    assert.equal(
      snapshotDeviceIdsMatchCache(cached, [
        { device_id: 'dev-1', state: 'online' },
        { device_id: 'dev-2', state: 'online' }
      ]),
      true
    );
    assert.equal(
      snapshotDeviceIdsMatchCache(cached, [{ device_id: 'dev-1', state: 'online' }]),
      false
    );
    assert.equal(
      snapshotDeviceIdsMatchCache(cached, [
        { device_id: 'dev-1', state: 'online' },
        { device_id: 'dev-2', state: 'online' },
        { device_id: 'dev-3', state: 'unknown' }
      ]),
      false
    );
  });

  it('applySnapshotToDevices patches FSM state only', () => {
    const cached = [device('dev-1', 'unknown')];
    const next = applySnapshotToDevices(cached, [
      { device_id: 'dev-1', state: 'online' }
    ]);
    assert.ok(next);
    assert.equal(next![0].state, 'online');
  });

  it('applyLifecycleEventToFleetStats skips stale replay shift', () => {
    const stats = fleetStats({
      unknown: 0,
      connecting: 0,
      online: 1,
      busy: 0,
      reconnecting: 0,
      dead: 0,
      total: 1
    });
    const cached = [device('dev-1', 'online')];
    const next = applyLifecycleEventToFleetStats(
      stats,
      {
        type: 'device.state_changed',
        event_id: 'e1',
        organization_id: 'org-1',
        device_id: 'dev-1',
        from_state: 'unknown',
        to_state: 'online',
        timestamp: '2026-05-29T00:00:00Z'
      },
      cached
    );
    assert.equal(next, null);
  });

  it('applyLifecycleEventToFleetStats shifts session owner on claim/release', () => {
    const stats = fleetStats(
      {
        unknown: 0,
        connecting: 0,
        online: 1,
        busy: 0,
        reconnecting: 0,
        dead: 0,
        total: 1
      },
      { user: 0, execution: 0, campaign: 0, system: 0, unknown: 0, total: 0 }
    );
    const cached = [device('dev-1', 'online')];

    const claimed = applyLifecycleEventToFleetStats(
      stats,
      {
        type: 'session.claimed',
        event_id: 'e2',
        organization_id: 'org-1',
        device_id: 'dev-1',
        from_state: 'online',
        to_state: 'busy',
        session_id: 'exec:run-1',
        timestamp: '2026-05-29T00:00:00Z'
      },
      cached
    );
    assert.ok(claimed);
    assert.equal(claimed!.devices.busy, 1);
    assert.equal(claimed!.devices.online, 0);
    assert.equal(claimed!.active_sessions.execution, 1);
    assert.equal(claimed!.active_sessions.total, 1);

    const busyCached = [device('dev-1', 'busy')];
    const released = applyLifecycleEventToFleetStats(
      claimed!,
      {
        type: 'session.released',
        event_id: 'e3',
        organization_id: 'org-1',
        device_id: 'dev-1',
        from_state: 'busy',
        to_state: 'online',
        session_id: 'exec:run-1',
        timestamp: '2026-05-29T00:00:00Z'
      },
      busyCached
    );
    assert.ok(released);
    assert.equal(released!.devices.online, 1);
    assert.equal(released!.active_sessions.execution, 0);
    assert.equal(released!.active_sessions.total, 0);
  });

  it('applyLifecycleEventToFleetStats shifts session owner even when device shift is stale', () => {
    const stats = fleetStats(
      {
        unknown: 0,
        connecting: 0,
        online: 1,
        busy: 0,
        reconnecting: 0,
        dead: 0,
        total: 1
      },
      { user: 0, execution: 0, campaign: 0, system: 0, unknown: 0, total: 0 }
    );
    const cached = [device('dev-1', 'online')];
    const next = applyLifecycleEventToFleetStats(
      stats,
      {
        type: 'session.claimed',
        event_id: 'e-stale',
        organization_id: 'org-1',
        device_id: 'dev-1',
        from_state: 'unknown',
        to_state: 'busy',
        session_id: 'exec:run-2',
        timestamp: '2026-05-29T00:00:00Z'
      },
      cached
    );
    assert.ok(next);
    assert.equal(next!.devices.online, 1);
    assert.equal(next!.active_sessions.execution, 1);
    assert.equal(next!.active_sessions.total, 1);
  });

  it('applyLifecycleEventToDevices removes unpaired device', () => {
    const cached = [device('dev-1', 'online'), device('dev-2', 'online')];
    const next = applyLifecycleEventToDevices(cached, {
      type: 'device.unpaired',
      event_id: 'e4',
      organization_id: 'org-1',
      device_id: 'dev-1',
      from_state: 'online',
      to_state: null,
      timestamp: '2026-05-29T00:00:00Z'
    });
    assert.ok(next);
    assert.equal(next!.length, 1);
    assert.equal(next![0].id, 'dev-2');
  });
});
