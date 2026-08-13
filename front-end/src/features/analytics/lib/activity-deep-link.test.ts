import assert from 'node:assert/strict';
import test from 'node:test';
import { activityLogDeepLink } from './activity-deep-link.ts';
import type { ActivityLogItem } from '../services/api.ts';

function item(partial: Partial<ActivityLogItem>): ActivityLogItem {
  return {
    id: '1',
    action: 'campaign.run',
    entity_type: null,
    entity_id: null,
    device_serial: null,
    details: {},
    created_at: '2026-01-01T00:00:00Z',
    ...partial
  } as ActivityLogItem;
}

test('activityLogDeepLink returns campaign run log for runtime campaign activity', () => {
  const link = activityLogDeepLink(
    item({
      entity_type: 'campaign',
      entity_id: 'camp-42',
      action: 'campaign.complete'
    })
  );
  assert.equal(link, '/dashboard/campaigns?campaign_id=camp-42&panel=run-log');
});

test('activityLogDeepLink returns campaign detail for non-runtime campaign entity', () => {
  const link = activityLogDeepLink(
    item({
      entity_type: 'campaign',
      entity_id: 'camp-42',
      action: 'campaign.updated'
    })
  );
  assert.equal(link, '/dashboard/campaigns?campaign_id=camp-42');
});

test('activityLogDeepLink returns campaign run log for execution activity', () => {
  const link = activityLogDeepLink(
    item({
      entity_type: 'execution',
      entity_id: 'exec-1',
      action: 'execution.failed',
      details: { campaign_id: 'camp-42' }
    })
  );
  assert.equal(
    link,
    '/dashboard/campaigns?campaign_id=camp-42&panel=run-log&execution_id=exec-1'
  );
});

test('activityLogDeepLink returns device detail for device serial', () => {
  const link = activityLogDeepLink(
    item({ device_serial: 'ABC123', action: 'device.connect' })
  );
  assert.equal(link, '/dashboard/devices/ABC123');
});

test('activityLogDeepLink returns schedules page for schedule_run entity', () => {
  const link = activityLogDeepLink(
    item({
      action: 'schedule.run.terminal',
      entity_type: 'schedule_run',
      entity_id: 'run-1',
      details: { schedule_id: 'sched-9' }
    })
  );
  assert.equal(link, '/dashboard/schedules?schedule_id=sched-9');
});

test('activityLogDeepLink returns org scenario detail for org_scenario entity', () => {
  const link = activityLogDeepLink(
    item({
      action: 'scenario.updated',
      entity_type: 'org_scenario',
      entity_id: 'sc-1'
    })
  );
  assert.equal(link, '/dashboard/org-scenarios?scenario_id=sc-1');
});

test('activityLogDeepLink returns content detail for content entity', () => {
  const link = activityLogDeepLink(
    item({ entity_type: 'content', entity_id: 'content-9' })
  );
  assert.equal(link, '/dashboard/content/content-9');
});
