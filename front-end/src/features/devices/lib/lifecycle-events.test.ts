import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  collectLifecycleEvents,
  collectSnapshotReplayEvents,
  isLifecycleWsMessage,
  lifecycleMessageNeedsRefresh
} from './lifecycle-events.ts';

describe('lifecycle-events', () => {
  it('recognizes lifecycle.event', () => {
    const msg = {
      type: 'lifecycle.event',
      event: {
        type: 'device.state_changed',
        event_id: 'e1',
        organization_id: 'org-1',
        device_id: 'dev-1',
        from_state: 'unknown',
        to_state: 'online',
        timestamp: '2026-05-29T00:00:00Z'
      }
    };
    assert.equal(isLifecycleWsMessage(msg), true);
    assert.equal(lifecycleMessageNeedsRefresh(msg), true);
  });

  it('snapshot with devices needs cache patch', () => {
    const msg = {
      type: 'lifecycle.snapshot',
      organization_id: 'org-1',
      devices: [{ device_id: 'dev-1', state: 'online' }],
      replay: []
    };
    assert.equal(lifecycleMessageNeedsRefresh(msg), true);
    assert.equal(collectLifecycleEvents(msg).length, 0);
  });

  it('batch refresh when any event matches', () => {
    const msg = {
      type: 'lifecycle.batch',
      organization_id: 'org-1',
      events: [
        {
          type: 'session.claimed',
          event_id: 'e2',
          organization_id: 'org-1',
          device_id: 'dev-1',
          from_state: 'online',
          to_state: 'busy',
          timestamp: '2026-05-29T00:00:00Z'
        }
      ]
    };
    assert.equal(lifecycleMessageNeedsRefresh(msg), true);
    assert.equal(collectLifecycleEvents(msg).length, 1);
  });

  it('snapshot replay is audit-only and not re-applied', () => {
    const msg = {
      type: 'lifecycle.snapshot',
      organization_id: 'org-1',
      devices: [{ device_id: 'dev-1', state: 'online' }],
      replay: [
        {
          type: 'device.state_changed',
          event_id: 'e-replay',
          organization_id: 'org-1',
          device_id: 'dev-1',
          from_state: 'unknown',
          to_state: 'connecting',
          timestamp: '2026-05-29T00:00:00Z'
        }
      ]
    };
    assert.equal(lifecycleMessageNeedsRefresh(msg), true);
    assert.equal(collectLifecycleEvents(msg).length, 0);
    assert.equal(collectSnapshotReplayEvents(msg).length, 1);
  });

  it('ignores pong', () => {
    assert.equal(lifecycleMessageNeedsRefresh({ type: 'pong' }), false);
  });
});
