import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowNode } from '../../../campaigns/components/scenario-steps/types.ts';
import {
  graphToSteps,
  moveScenarioNode
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../../../campaigns/utils/scenario-graph.ts';

function node(
  id: string,
  order: string,
  scope: FlowNode['scope'] = null,
  type = 'wait',
  config: Record<string, unknown> = {}
): FlowNode {
  return { id, type, config, order, scope };
}

test('canonical graph reorder keeps stable node identity', () => {
  const nodes = [node('a', 'a0'), node('b', 'a1'), node('c', 'a2')];
  const moved = moveScenarioNode({ nodes, edges: [] }, 'c', null, null);

  assert.ok(moved);
  assert.deepEqual(
    graphToSteps(moved.nodes).map((step) => step.id),
    ['c', 'a', 'b']
  );
  assert.deepEqual(
    new Set(moved.nodes.map((item) => item.id)),
    new Set(['a', 'b', 'c'])
  );
});

test('canonical graph moves nodes across branch scopes', () => {
  const nodes = [
    node('condition', 'a0', null, 'if_element'),
    node('root', 'a1'),
    node('then-step', 'a0', { parentId: 'condition', branch: 'then' })
  ];
  const moved = moveScenarioNode(
    { nodes, edges: [] },
    'root',
    { parentId: 'condition', branch: 'then' },
    'then-step'
  );

  assert.ok(moved);
  const [condition] = graphToSteps(moved.nodes);
  assert.deepEqual(
    condition.then.map((step: any) => step.id),
    ['then-step', 'root']
  );
});

test('canonical graph rejects moving a container into its descendant', () => {
  const nodes = [
    node('loop', 'a0', null, 'repeat'),
    node('child', 'a0', { parentId: 'loop', branch: 'steps' })
  ];

  assert.equal(
    moveScenarioNode(
      { nodes, edges: [] },
      'loop',
      { parentId: 'child', branch: 'steps' },
      null
    ),
    null
  );
});
