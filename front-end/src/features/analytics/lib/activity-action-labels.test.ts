import assert from 'node:assert/strict';
import test from 'node:test';
import type { ActivityLogItem } from '../services/api.ts';
import {
  formatActivityStatus,
  resolveActivityActionLabel,
  resolveDedicatedActivityTitle,
  resolveDomainActivityDescription
} from './activity-action-labels.ts';

const t = (key: string, values?: Record<string, string | number>) => {
  const table: Record<string, string> = {
    'actionLabels.execution_cancelled': 'Execution cancelled',
    'actionLabels.session_released_execution_terminal':
      'Session released (run ended)',
    'titles.campaignStatusChanged': 'Campaign: {from} → {to}',
    'titles.scenarioUpdatedGeneric': 'Scenario updated',
    'statusLabels.running': 'Running',
    'statusLabels.cancelled': 'Cancelled',
    'releaseReasonLabels.execution_terminal': 'Run finished',
    contextCampaign: 'Campaign {id}',
    contextCampaignGeneric: 'Campaign',
    contextExecutionGeneric: 'Scenario run',
    contextScenarioGeneric: 'Scenario',
    deviceSerial: 'Device {serial}'
  };
  let out = table[key] ?? key;
  if (values) {
    for (const [k, v] of Object.entries(values)) {
      out = out.replace(`{${k}}`, String(v));
    }
  }
  return out;
};

function item(
  partial: Partial<ActivityLogItem> & Pick<ActivityLogItem, 'action'>
): ActivityLogItem {
  return {
    id: '1',
    action: partial.action,
    entity_type: partial.entity_type ?? null,
    entity_id: partial.entity_id ?? null,
    device_serial: partial.device_serial ?? null,
    device_display: partial.device_display ?? null,
    org_id: partial.org_id ?? null,
    user_id: partial.user_id ?? null,
    user_name: partial.user_name ?? null,
    method: null,
    path: null,
    route_template: null,
    status_code: null,
    request_id: null,
    ip_address: null,
    user_agent: null,
    outcome: null,
    duration_ms: null,
    details: partial.details ?? {},
    created_at: '2026-06-04T10:27:00Z'
  } as ActivityLogItem;
}

test('resolveActivityActionLabel maps execution.cancelled', () => {
  const label = resolveActivityActionLabel('execution.cancelled', t);
  assert.equal(label, 'Execution cancelled');
  assert.ok(!label.includes('·'));
});

test('resolveDedicatedActivityTitle for campaign.status.changed', () => {
  const title = resolveDedicatedActivityTitle(
    item({
      action: 'campaign.status.changed',
      details: { from: 'running', to: 'cancelled' }
    }),
    t
  );
  assert.equal(title, 'Campaign: Running → Cancelled');
});

test('resolveDedicatedActivityTitle for scenario.updated', () => {
  assert.equal(
    resolveDedicatedActivityTitle(item({ action: 'scenario.updated' }), t),
    'Scenario updated'
  );
});

test('resolveDedicatedActivityTitle for schedule.run.terminal', () => {
  const table: Record<string, string> = {
    'titles.scheduleRunTerminal': 'Scheduled run finished ({status})',
    'statusLabels.completed': 'Completed'
  };
  const t2 = (key: string, values?: Record<string, string | number>) => {
    let out = table[key] ?? key;
    if (values) {
      for (const [k, v] of Object.entries(values)) {
        out = out.replace(`{${k}}`, String(v));
      }
    }
    return out;
  };
  assert.equal(
    resolveDedicatedActivityTitle(
      item({
        action: 'schedule.run.terminal',
        details: { status: 'completed' }
      }),
      t2
    ),
    'Scheduled run finished (Completed)'
  );
});

test('formatActivityStatus falls back from fully qualified missing i18n key', () => {
  assert.equal(
    formatActivityStatus(
      'unknown_status',
      (key) => `analyticsFeature.activity.${key}`
    ),
    'unknown status'
  );
});

test('resolveDomainActivityDescription includes release context', () => {
  const line = resolveDomainActivityDescription(
    item({
      action: 'session.released.execution_terminal',
      device_serial: 'ABC123',
      details: {
        campaign_id: 'camp-uuid-long-1234',
        release_reason: 'execution_terminal'
      }
    }),
    t,
    (serial) => `Device ${serial}`
  );
  assert.ok(line?.includes('Run finished'));
  assert.ok(line?.includes('ABC123'));
});

test('resolveDomainActivityDescription hides technical campaign id', () => {
  const line = resolveDomainActivityDescription(
    item({
      action: 'campaign.dlq_opened',
      details: {
        campaign_id: '0ce1c7e0-d9e9-4a0d-ae6b-331f84836f16'
      }
    }),
    t,
    (serial) => `Device ${serial}`
  );
  assert.ok(line?.includes('Campaign'));
  assert.ok(!line?.includes('0ce1c7e0'));
});
