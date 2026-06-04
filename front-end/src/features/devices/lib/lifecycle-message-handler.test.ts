/**
 * QueryClient integration for lifecycle message handler (DF-T-02-015).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { QueryClient } from '@tanstack/react-query';
import type { DeviceOut, FleetStatsOut } from '../services/manage-api.ts';
import { applyLifecycleMessage } from './lifecycle-message-handler.ts';
import { DEVICES_LIST_KEY, FLEET_STATS_KEY } from './device-query-keys.ts';

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

describe('lifecycle message handler (QueryClient)', () => {
  it('UC-HC-01: applies live event to React Query cache', () => {
    const qc = new QueryClient();
    qc.setQueryData(DEVICES_LIST_KEY, [device('dev-1', 'online')]);
    qc.setQueryData(FLEET_STATS_KEY, {
      filters: { organization_id: 'org-1', group_id: null, relay_host: null },
      devices: {
        unknown: 0,
        connecting: 0,
        online: 1,
        busy: 0,
        reconnecting: 0,
        dead: 0,
        total: 1
      },
      active_sessions: {
        user: 0,
        execution: 0,
        campaign: 0,
        system: 0,
        unknown: 0,
        total: 0
      },
      owner_anomalies: null
    } satisfies FleetStatsOut);

    applyLifecycleMessage(qc, {
      type: 'lifecycle.event',
      event: {
        type: 'session.claimed',
        event_id: 'hc-1',
        organization_id: 'org-1',
        device_id: 'dev-1',
        from_state: 'online',
        to_state: 'busy',
        session_id: 'exec:hc',
        timestamp: '2026-05-29T12:00:00Z'
      }
    });

    assert.equal(
      qc.getQueryData<DeviceOut[]>(DEVICES_LIST_KEY)![0].state,
      'busy'
    );
    assert.equal(
      qc.getQueryData<FleetStatsOut>(FLEET_STATS_KEY)!.active_sessions
        .execution,
      1
    );
  });

  it('UC-HC-02: device-set mismatch snapshot triggers invalidateQueries', () => {
    const qc = new QueryClient();
    const invalidated: string[][] = [];
    const original = qc.invalidateQueries.bind(qc);
    qc.invalidateQueries = ((opts) => {
      if (Array.isArray(opts?.queryKey)) {
        invalidated.push([...opts.queryKey] as string[]);
      }
      return original(opts);
    }) as typeof qc.invalidateQueries;

    qc.setQueryData(DEVICES_LIST_KEY, [
      device('dev-1', 'online'),
      device('dev-2', 'online')
    ]);

    applyLifecycleMessage(qc, {
      type: 'lifecycle.snapshot',
      organization_id: 'org-1',
      devices: [{ device_id: 'dev-1', state: 'online' }],
      replay: []
    });

    assert.ok(invalidated.some((k) => k.length === 1 && k[0] === 'devices'));
    assert.ok(
      invalidated.some((k) => k[0] === 'devices' && k[1] === 'fleet-stats')
    );
  });
});
