import assert from 'node:assert/strict';
import test from 'node:test';
import {
  artifactIsFailShot,
  filterArtifactsByDevice,
  groupArtifactsByDevice,
  neighborArtifactKeys,
  uniqueDeviceSerials,
  sortExecutionsForArtifactPanel,
  pickDefaultExecutionId,
  filterExecutionsWithShots,
  type ResolvedMonitorArtifact
} from './artifact-panel-model.ts';
import type { ExecutionArtifact } from '../types.ts';

function mockArtifact(
  overrides: Partial<ExecutionArtifact> & Pick<ExecutionArtifact, 'artifact_type'>
): ExecutionArtifact {
  return {
    execution_id: 'exec-1',
    device_serial: 'V2352A',
    step_index: 2,
    step_type: 'tap',
    ok: true,
    message: null,
    url: '/artifacts/x.jpg',
    metadata: {},
    created_at: '2026-06-21T14:06:33Z',
    ...overrides
  };
}

function mockResolved(
  overrides: Partial<ResolvedMonitorArtifact> & Pick<ResolvedMonitorArtifact, 'key'>
): ResolvedMonitorArtifact {
  return {
    artifact: mockArtifact({ artifact_type: 'screenshot_post' }),
    href: '/artifacts/x.jpg',
    deviceLabel: 'V2352A',
    subtitle: 'Step 3: tap',
    isFail: false,
    stepNumber: 3,
    timeLabel: '14:06:33',
    ...overrides
  };
}

test('artifactIsFailShot detects fail screenshots', () => {
  assert.equal(
    artifactIsFailShot(mockArtifact({ artifact_type: 'fail.screenshot' })),
    true
  );
  assert.equal(
    artifactIsFailShot(mockArtifact({ artifact_type: 'screenshot_post', ok: false })),
    true
  );
  assert.equal(
    artifactIsFailShot(mockArtifact({ artifact_type: 'screenshot_pre' })),
    false
  );
});

test('groupArtifactsByDevice preserves device order and filters', () => {
  const items = [
    mockResolved({ key: 'a', deviceLabel: 'V2352A' }),
    mockResolved({ key: 'b', deviceLabel: '10AE' }),
    mockResolved({ key: 'c', deviceLabel: 'V2352A' })
  ];
  const grouped = groupArtifactsByDevice(items, 'all');
  assert.equal(grouped.length, 2);
  assert.equal(grouped[0]!.device, 'V2352A');
  assert.equal(grouped[0]!.shots.length, 2);
  assert.equal(groupArtifactsByDevice(items, '10AE')[0]!.shots.length, 1);
});

test('uniqueDeviceSerials returns first-seen order', () => {
  const items = [
    mockResolved({ key: 'a', deviceLabel: 'B' }),
    mockResolved({ key: 'b', deviceLabel: 'A' }),
    mockResolved({ key: 'c', deviceLabel: 'B' })
  ];
  assert.deepEqual(uniqueDeviceSerials(items), ['B', 'A']);
});

test('neighborArtifactKeys walks filtered list', () => {
  const items = [
    mockResolved({ key: 'a' }),
    mockResolved({ key: 'b' }),
    mockResolved({ key: 'c' })
  ];
  assert.deepEqual(neighborArtifactKeys(items, 'b'), {
    prev: 'a',
    next: 'c'
  });
  assert.deepEqual(neighborArtifactKeys(items, 'a'), {
    prev: null,
    next: 'b'
  });
});

test('filterArtifactsByDevice keeps all when filter is all', () => {
  const items = [mockResolved({ key: 'a' }), mockResolved({ key: 'b', deviceLabel: 'X' })];
  assert.equal(filterArtifactsByDevice(items, 'all').length, 2);
});

test('sortExecutionsForArtifactPanel puts runs with shots first', () => {
  const executions = [
    { id: 'empty', status: 'completed', created_at: '2026-06-21T10:00:00Z', run_type: 'campaign', campaign_id: 'c1', scenario_id: null, started_at: null, finished_at: null },
    { id: 'shots', status: 'failed', created_at: '2026-06-20T10:00:00Z', run_type: 'campaign', campaign_id: 'c1', scenario_id: null, started_at: null, finished_at: null }
  ] as import('../types.ts').ExecutionOut[];
  const counts = new Map([
    ['empty', 0],
    ['shots', 2]
  ]);
  const sorted = sortExecutionsForArtifactPanel(executions, counts);
  assert.equal(sorted[0]!.id, 'shots');
});

test('pickDefaultExecutionId prefers first run with shots', () => {
  const executions = [
    { id: 'empty', status: 'completed', created_at: '2026-06-21T10:00:00Z', run_type: 'campaign', campaign_id: 'c1', scenario_id: null, started_at: null, finished_at: null },
    { id: 'shots', status: 'failed', created_at: '2026-06-20T10:00:00Z', run_type: 'campaign', campaign_id: 'c1', scenario_id: null, started_at: null, finished_at: null }
  ] as import('../types.ts').ExecutionOut[];
  const counts = new Map([
    ['empty', 0],
    ['shots', 1]
  ]);
  assert.equal(pickDefaultExecutionId(executions, counts, null), 'shots');
  assert.equal(pickDefaultExecutionId(executions, counts, 'empty'), 'empty');
});

test('filterExecutionsWithShots hides empty runs when enabled', () => {
  const executions = [
    { id: 'empty', status: 'completed', created_at: '2026-06-21T10:00:00Z', run_type: 'campaign', campaign_id: 'c1', scenario_id: null, started_at: null, finished_at: null },
    { id: 'shots', status: 'failed', created_at: '2026-06-20T10:00:00Z', run_type: 'campaign', campaign_id: 'c1', scenario_id: null, started_at: null, finished_at: null }
  ] as import('../types.ts').ExecutionOut[];
  const counts = new Map([
    ['empty', 0],
    ['shots', 3]
  ]);
  assert.equal(filterExecutionsWithShots(executions, counts, true).length, 1);
  assert.equal(filterExecutionsWithShots(executions, counts, false).length, 2);
});
