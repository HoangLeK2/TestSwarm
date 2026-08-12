import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowEdge, FlowNode } from '../components/scenario-steps/types.ts';
import {
  graphToSteps,
  moveScenarioNode
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './scenario-graph.ts';

function node(
  id: string,
  order: string,
  scope: FlowNode['scope'] = null,
  type = 'wait',
  config: Record<string, unknown> = {}
): FlowNode {
  return { id, type, config, order, scope };
}

function pairs(edges: FlowEdge[]): string[] {
  return edges
    .filter((edge) => edge.type === 'default')
    .map((edge) => `${edge.source}->${edge.target}`)
    .sort();
}

test('moveScenarioNode reorders siblings with stable IDs and rewires edges', () => {
  const nodes = [node('a', 'a0'), node('b', 'a1'), node('c', 'a2')];
  const edges: FlowEdge[] = [
    { id: 'ab', source: 'a', target: 'b', type: 'default' },
    { id: 'bc', source: 'b', target: 'c', type: 'default' }
  ];

  const moved = moveScenarioNode({ nodes, edges }, 'c', null, null);

  assert.ok(moved);
  assert.deepEqual(
    graphToSteps(moved.nodes).map((step) => step.id),
    ['c', 'a', 'b']
  );
  assert.equal(moved.nodes.find((item) => item.id === 'c')?.id, 'c');
  assert.deepEqual(pairs(moved.edges), ['a->b', 'c->a']);
  assert.deepEqual(
    nodes.map((item) => item.order),
    ['a0', 'a1', 'a2']
  );
});

test('moveScenarioNode moves root node into and out of a branch', () => {
  const branch = { parentId: 'condition', branch: 'then' };
  const nodes = [
    node('move-me', 'a0'),
    node('condition', 'a1', null, 'if_element'),
    node('inside', 'a0', branch, 'tap_selector')
  ];

  const nested = moveScenarioNode(
    { nodes, edges: [] },
    'move-me',
    branch,
    'inside'
  );
  assert.ok(nested);
  const nestedSteps = graphToSteps(nested.nodes);
  assert.deepEqual(
    nestedSteps.map((step) => step.id),
    ['condition']
  );
  assert.deepEqual(
    nestedSteps[0].then.map((step: any) => step.id),
    ['inside', 'move-me']
  );

  const rooted = moveScenarioNode(nested, 'move-me', null, 'condition');
  assert.ok(rooted);
  assert.deepEqual(
    graphToSteps(rooted.nodes).map((step) => step.id),
    ['condition', 'move-me']
  );
});

test('moveScenarioNode moves between random branches and preserves empty arms', () => {
  const nodes = [
    node('random', 'a0', null, 'random_pick', {
      branch_weights: [2, 1, 4]
    }),
    node('move-me', 'a0', { parentId: 'random', branch: 'branch_0' }),
    node('target', 'a0', { parentId: 'random', branch: 'branch_1' })
  ];

  const moved = moveScenarioNode(
    { nodes, edges: [] },
    'move-me',
    { parentId: 'random', branch: 'branch_1' },
    null
  );

  assert.ok(moved);
  const [random] = graphToSteps(moved.nodes);
  assert.deepEqual(
    random.branches.map((branch: any) => ({
      weight: branch.weight,
      ids: branch.steps.map((step: any) => step.id)
    })),
    [
      { weight: 2, ids: [] },
      { weight: 1, ids: ['move-me', 'target'] },
      { weight: 4, ids: [] }
    ]
  );
});

test('moveScenarioNode rejects descendants and invalid predecessors', () => {
  const nodes = [
    node('loop', 'a0', null, 'repeat'),
    node('inside', 'a0', { parentId: 'loop', branch: 'steps' })
  ];

  assert.equal(
    moveScenarioNode(
      { nodes, edges: [] },
      'loop',
      { parentId: 'inside', branch: 'steps' },
      null
    ),
    null
  );
  assert.equal(
    moveScenarioNode({ nodes, edges: [] }, 'inside', null, 'missing'),
    null
  );
});

test('graphToSteps compiles nested loop, condition, and stable metadata', () => {
  const nodes = [
    node('loop', 'a0', null, 'repeat', { count: 2 }),
    node(
      'condition',
      'a0',
      { parentId: 'loop', branch: 'steps' },
      'if_variable',
      {
        name: 'ready',
        equals: true
      }
    ),
    node(
      'yes',
      'a0',
      { parentId: 'condition', branch: 'then' },
      'tap_selector'
    ),
    node('no', 'a0', { parentId: 'condition', branch: 'else' }, 'wait')
  ];

  const [loop] = graphToSteps(nodes);

  assert.equal(loop.id, 'loop');
  assert.equal(loop.order, 'a0');
  assert.equal(loop.count, 2);
  assert.equal(loop.steps[0].id, 'condition');
  assert.equal(loop.steps[0].then[0].id, 'yes');
  assert.equal(loop.steps[0].else[0].id, 'no');
});
