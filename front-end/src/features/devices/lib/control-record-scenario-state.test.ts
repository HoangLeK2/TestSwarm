import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowStep } from '../../campaigns/components/scenario-steps/types';
import {
  buildControlRecordScenarioSnapshot
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './control-record-scenario-state.ts';

test('snapshot keeps canonical IDs and synchronizes reordered graph nodes', () => {
  const snapshot = buildControlRecordScenarioSnapshot([
    { id: 'second', order: 'old-2', type: 'wait', seconds: 2 },
    { id: 'first', order: 'old-1', type: 'wait', seconds: 1 }
  ]);

  assert.deepEqual(
    snapshot.steps.map((step) => step.id),
    ['second', 'first']
  );
  assert.deepEqual(
    snapshot.nodes.map((node) => node.id),
    ['second', 'first']
  );
  assert.ok(snapshot.steps[0]!.order < snapshot.steps[1]!.order);
  assert.equal(snapshot.nodes[0]!.order, snapshot.steps[0]!.order);
  assert.equal(snapshot.nodes[1]!.order, snapshot.steps[1]!.order);
  assert.deepEqual(
    snapshot.edges.map((edge) => [edge.source, edge.target]),
    [['second', 'first']]
  );
});

test('snapshot assigns identity recursively and preserves empty random branches', () => {
  const snapshot = buildControlRecordScenarioSnapshot([
    {
      id: 'random',
      type: 'random_pick',
      branches: [
        { weight: 3, steps: [] },
        { weight: 1, steps: [{ type: 'wait', seconds: 1 }] }
      ]
    }
  ]);
  const random = snapshot.steps[0] as unknown as FlowStep & {
    branches: Array<{ weight: number; steps: FlowStep[] }>;
  };
  const child = random.branches[1]!.steps[0]!;
  const randomNode = snapshot.nodes.find((node) => node.id === 'random');
  const childNode = snapshot.nodes.find((node) => node.id === child.id);

  assert.equal(random.branches.length, 2);
  assert.deepEqual(random.branches[0], { weight: 3, steps: [] });
  assert.equal(typeof child.id, 'string');
  assert.equal(child._id, child.id);
  assert.deepEqual(randomNode?.config.branch_weights, [3, 1]);
  assert.deepEqual(childNode?.scope, {
    parentId: 'random',
    branch: 'branch_1'
  });
});

test('snapshot keeps editor identity outside graph node config', () => {
  const snapshot = buildControlRecordScenarioSnapshot([
    {
      id: 'wait-id',
      _id: 'react-id',
      _fgId: 'wait-id',
      order: 'stale-order',
      type: 'wait',
      seconds: 2
    }
  ]);

  assert.deepEqual(snapshot.nodes[0]?.config, { seconds: 2 });
});

test('snapshot regenerates duplicate canonical IDs across nested scopes', () => {
  const snapshot = buildControlRecordScenarioSnapshot([
    { id: 'duplicate', type: 'wait', seconds: 1 },
    {
      id: 'condition',
      type: 'if',
      then: [{ id: 'duplicate', type: 'wait', seconds: 2 }],
      else: []
    }
  ]);
  const ids = snapshot.nodes.map((node) => node.id);

  assert.equal(ids[0], 'duplicate');
  assert.equal(new Set(ids).size, ids.length);
  assert.notEqual(ids[2], 'duplicate');
  assert.deepEqual(snapshot.nodes[2]?.scope, {
    parentId: 'condition',
    branch: 'then'
  });
});
