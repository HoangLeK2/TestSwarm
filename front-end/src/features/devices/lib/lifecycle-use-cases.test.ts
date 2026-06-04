/**
 * Use-case tests for lifecycle WS → dashboard cache (DF-T-02-015).
 *
 * Scenarios mirror operator flows on /dashboard/devices.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { DeviceOut, FleetStatsOut } from '../services/manage-api.ts';
import {
  applyLifecycleMessageSequence,
  applyLifecycleMessageToCache
} from './lifecycle-realtime-apply.ts';
import type { DeviceLifecycleEventPayload } from './lifecycle-events.ts';

function device(id: string, state: string): DeviceOut {
  return {
    id,
    serial: `serial-${id}`,
    name: `Phone ${id}`,
    device_key: 'k',
    user_id: null,
    brand: 'Google',
    model: 'Pixel',
    android_version: '14',
    sdk_version: 34,
    screen_width: 1080,
    screen_height: 2400,
    last_seen: '2026-05-29T12:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    adb_serial: null,
    adb_ip: null,
    adb_port: 5555,
    state
  };
}

function fleetCounts(
  partial: Partial<FleetStatsOut['devices']> & { total: number }
): FleetStatsOut['devices'] {
  return {
    unknown: 0,
    connecting: 0,
    online: 0,
    busy: 0,
    reconnecting: 0,
    dead: 0,
    ...partial
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

function liveEvent(
  partial: Partial<DeviceLifecycleEventPayload> & {
    type: DeviceLifecycleEventPayload['type'];
    device_id: string;
    from_state: string | null;
    to_state: string | null;
  }
): DeviceLifecycleEventPayload {
  return {
    event_id: partial.event_id ?? 'evt-1',
    organization_id: partial.organization_id ?? 'org-1',
    timestamp: partial.timestamp ?? '2026-05-29T12:00:00Z',
    ...partial
  };
}

const initialTwoOnline = {
  devices: [device('dev-1', 'online'), device('dev-2', 'online')],
  fleetStats: fleetStats(fleetCounts({ online: 2, total: 2 }))
};

describe('lifecycle use cases (dashboard realtime)', () => {
  it('UC-01: WS reconnect patches FSM state when device set unchanged', () => {
    const result = applyLifecycleMessageToCache(
      {
        devices: [device('dev-1', 'reconnecting')],
        fleetStats: fleetStats(fleetCounts({ reconnecting: 1, total: 1 }))
      },
      {
        type: 'lifecycle.snapshot',
        organization_id: 'org-1',
        devices: [{ device_id: 'dev-1', state: 'online' }],
        replay: []
      }
    );

    assert.equal(result.cache.devices?.[0]?.state, 'online');
    assert.equal(result.cache.fleetStats?.devices.online, 1);
    assert.equal(result.cache.fleetStats?.devices.reconnecting, 0);
    assert.deepEqual(result.invalidate, []);
  });

  it('UC-02: device deleted on server while tab idle triggers refetch', () => {
    const result = applyLifecycleMessageToCache(initialTwoOnline, {
      type: 'lifecycle.snapshot',
      organization_id: 'org-1',
      devices: [{ device_id: 'dev-1', state: 'online' }],
      replay: []
    });

    assert.deepEqual(result.invalidate, ['devices', 'fleet-stats']);
  });

  it('UC-03: new device on server while tab idle triggers refetch', () => {
    const result = applyLifecycleMessageToCache(
      {
        devices: [device('dev-1', 'online')],
        fleetStats: fleetStats(fleetCounts({ online: 1, total: 1 }))
      },
      {
        type: 'lifecycle.snapshot',
        organization_id: 'org-1',
        devices: [
          { device_id: 'dev-1', state: 'online' },
          { device_id: 'dev-2', state: 'unknown' }
        ],
        replay: []
      }
    );

    assert.deepEqual(result.invalidate, ['devices', 'fleet-stats']);
  });

  it('UC-04/05: claim then release updates device row and fleet session counts', () => {
    const result = applyLifecycleMessageSequence(
      {
        devices: [device('dev-1', 'online')],
        fleetStats: fleetStats(fleetCounts({ online: 1, total: 1 }))
      },
      [
        {
          type: 'lifecycle.event',
          event: liveEvent({
            type: 'session.claimed',
            device_id: 'dev-1',
            from_state: 'online',
            to_state: 'busy',
            session_id: 'exec:campaign-run-42'
          })
        },
        {
          type: 'lifecycle.event',
          event: liveEvent({
            type: 'session.released',
            event_id: 'evt-2',
            device_id: 'dev-1',
            from_state: 'busy',
            to_state: 'online',
            session_id: 'exec:campaign-run-42'
          })
        }
      ]
    );

    assert.equal(result.cache.devices?.[0]?.state, 'online');
    assert.equal(result.cache.fleetStats?.devices.online, 1);
    assert.equal(result.cache.fleetStats?.devices.busy, 0);
    assert.equal(result.cache.fleetStats?.active_sessions.execution, 0);
    assert.equal(result.cache.fleetStats?.active_sessions.total, 0);
  });

  it('UC-06: device.unpaired removes row and decrements fleet totals', () => {
    const result = applyLifecycleMessageToCache(
      {
        devices: [device('dev-1', 'online'), device('dev-2', 'dead')],
        fleetStats: fleetStats(fleetCounts({ online: 1, dead: 1, total: 2 }))
      },
      {
        type: 'lifecycle.event',
        event: liveEvent({
          type: 'device.unpaired',
          device_id: 'dev-1',
          from_state: 'online',
          to_state: null
        })
      }
    );

    assert.equal(result.cache.devices?.length, 1);
    assert.equal(result.cache.devices?.[0]?.id, 'dev-2');
    assert.equal(result.cache.fleetStats?.devices.total, 1);
    assert.equal(result.cache.fleetStats?.devices.online, 0);
  });

  it('UC-07: reconnecting→dead in snapshot replay notifies operator only', () => {
    const result = applyLifecycleMessageToCache(
      {
        devices: [device('dev-1', 'online')],
        fleetStats: fleetStats(fleetCounts({ online: 1, total: 1 }))
      },
      {
        type: 'lifecycle.snapshot',
        organization_id: 'org-1',
        devices: [{ device_id: 'dev-1', state: 'online' }],
        replay: [
          liveEvent({
            type: 'device.state_changed',
            event_id: 'dead-replay',
            device_id: 'dev-1',
            from_state: 'reconnecting',
            to_state: 'dead',
            payload: { reason: 'reconnect_timeout' }
          })
        ]
      }
    );

    assert.equal(result.notifyEvents.length, 1);
    assert.equal(result.notifyEvents[0]?.to_state, 'dead');
    assert.deepEqual(result.invalidate, []);
    assert.equal(result.cache.fleetStats?.devices.online, 1);
  });

  it('UC-08: lifecycle.batch applies multiple device updates', () => {
    const result = applyLifecycleMessageToCache(initialTwoOnline, {
      type: 'lifecycle.batch',
      organization_id: 'org-1',
      events: [
        liveEvent({
          type: 'session.claimed',
          event_id: 'c1',
          device_id: 'dev-1',
          from_state: 'online',
          to_state: 'busy',
          session_id: 'exec:a'
        }),
        liveEvent({
          type: 'session.claimed',
          event_id: 'c2',
          device_id: 'dev-2',
          from_state: 'online',
          to_state: 'busy',
          session_id: 'exec:b'
        })
      ]
    });

    assert.equal(result.cache.devices?.[0]?.state, 'busy');
    assert.equal(result.cache.devices?.[1]?.state, 'busy');
    assert.equal(result.cache.fleetStats?.devices.busy, 2);
    assert.equal(result.cache.fleetStats?.active_sessions.execution, 2);
  });

  it('UC-09: empty device cache on snapshot requests HTTP refetch', () => {
    const result = applyLifecycleMessageToCache(
      { devices: undefined, fleetStats: fleetStats(fleetCounts({ total: 0 })) },
      {
        type: 'lifecycle.snapshot',
        organization_id: 'org-1',
        devices: [{ device_id: 'dev-1', state: 'online' }],
        replay: []
      }
    );

    assert.deepEqual(result.invalidate, ['devices', 'fleet-stats']);
  });

  it('UC-10: stale replay in snapshot does not double-shift fleet counts', () => {
    const result = applyLifecycleMessageToCache(
      {
        devices: [device('dev-1', 'online')],
        fleetStats: fleetStats(fleetCounts({ online: 1, total: 1 }))
      },
      {
        type: 'lifecycle.snapshot',
        organization_id: 'org-1',
        devices: [{ device_id: 'dev-1', state: 'online' }],
        replay: [
          liveEvent({
            type: 'device.state_changed',
            event_id: 'replay-stale',
            device_id: 'dev-1',
            from_state: 'unknown',
            to_state: 'online'
          })
        ]
      }
    );

    assert.equal(result.cache.fleetStats?.devices.online, 1);
    assert.equal(result.cache.fleetStats?.devices.total, 1);
    assert.equal(result.cache.fleetStats?.devices.unknown, 0);
  });

  it('UC-11: live reconnecting→dead notifies operator and updates row', () => {
    const result = applyLifecycleMessageToCache(
      {
        devices: [device('dev-1', 'reconnecting')],
        fleetStats: fleetStats(fleetCounts({ reconnecting: 1, total: 1 }))
      },
      {
        type: 'lifecycle.event',
        event: liveEvent({
          type: 'device.state_changed',
          event_id: 'live-dead',
          device_id: 'dev-1',
          from_state: 'reconnecting',
          to_state: 'dead',
          payload: { reason: 'agent_lost' }
        })
      }
    );

    assert.equal(result.cache.devices?.[0]?.state, 'dead');
    assert.equal(result.cache.fleetStats?.devices.dead, 1);
    assert.equal(result.cache.fleetStats?.devices.reconnecting, 0);
    assert.equal(result.notifyEvents.length, 1);
    assert.equal(result.notifyEvents[0]?.event_id, 'live-dead');
  });

  it('UC-12: full operator flow claim → release → unpair via message sequence', () => {
    const result = applyLifecycleMessageSequence(
      {
        devices: [device('dev-1', 'online')],
        fleetStats: fleetStats(fleetCounts({ online: 1, total: 1 }))
      },
      [
        {
          type: 'lifecycle.event',
          event: liveEvent({
            type: 'session.claimed',
            event_id: 'seq-claim',
            device_id: 'dev-1',
            from_state: 'online',
            to_state: 'busy',
            session_id: 'exec:seq-1'
          })
        },
        {
          type: 'lifecycle.event',
          event: liveEvent({
            type: 'session.released',
            event_id: 'seq-release',
            device_id: 'dev-1',
            from_state: 'busy',
            to_state: 'online',
            session_id: 'exec:seq-1'
          })
        },
        {
          type: 'lifecycle.event',
          event: liveEvent({
            type: 'device.unpaired',
            event_id: 'seq-unpair',
            device_id: 'dev-1',
            from_state: 'online',
            to_state: null
          })
        }
      ]
    );

    assert.equal(result.cache.devices?.length, 0);
    assert.equal(result.cache.fleetStats?.devices.total, 0);
    assert.equal(result.cache.fleetStats?.active_sessions.total, 0);
    assert.equal(result.notifyEvents.length, 3);
  });

  it('UC-13: session owner counts update even when device FSM shift is stale', () => {
    const result = applyLifecycleMessageToCache(
      {
        devices: [device('dev-1', 'online')],
        fleetStats: fleetStats(fleetCounts({ online: 1, total: 1 }))
      },
      {
        type: 'lifecycle.event',
        event: liveEvent({
          type: 'session.claimed',
          event_id: 'stale-fsm',
          device_id: 'dev-1',
          from_state: 'unknown',
          to_state: 'busy',
          session_id: 'exec:stale'
        })
      }
    );

    assert.equal(result.cache.fleetStats?.devices.online, 1);
    assert.equal(result.cache.fleetStats?.active_sessions.execution, 1);
    assert.equal(result.cache.fleetStats?.active_sessions.total, 1);
  });
});
