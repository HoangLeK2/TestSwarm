import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowNode } from '../../../campaigns/components/scenario-steps/types.ts';
import {
  moveScenarioNode
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../../../campaigns/utils/scenario-graph.ts';
import {
  layoutScenarioAutomation,
  SCENARIO_END_ID,
  SCENARIO_START_ID,
  scenarioStepNodeId
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './scenario-automation-layout.ts';

function node(
  id: string,
  order: string,
  scope: FlowNode['scope'] = null,
  type = 'wait',
  config: Record<string, unknown> = {}
): FlowNode {
  return { id, type, config, order, scope };
}

test('ELK lays out a linear canonical graph from left to right', async () => {
  const layout = await layoutScenarioAutomation([
    node('a', 'a0'),
    node('b', 'a1', null, 'tap_selector'),
    node('c', 'a2', null, 'input_selector')
  ]);
  const byId = new Map(layout.nodes.map((item) => [item.id, item]));

  assert.ok(
    byId.get(SCENARIO_START_ID)!.position.x < byId.get('a')!.position.x
  );
  assert.ok(byId.get('a')!.position.x < byId.get('b')!.position.x);
  assert.ok(byId.get('b')!.position.x < byId.get('c')!.position.x);
  assert.ok(byId.get('c')!.position.x < byId.get(SCENARIO_END_ID)!.position.x);
  assert.ok(layout.edges.every((edge) => edge.points.length >= 2));
});

test('ELK gives canonical condition scopes distinct lanes', async () => {
  const nodes = [
    node('condition', 'a0', null, 'if_element'),
    node(
      'then-step',
      'a0',
      { parentId: 'condition', branch: 'then' },
      'tap_selector'
    ),
    node('else-step', 'a0', { parentId: 'condition', branch: 'else' }),
    node('after', 'a1', null, 'take_screenshot')
  ];
  const layout = await layoutScenarioAutomation(nodes);
  const frames = layout.nodes.filter((item) => item.kind === 'frame');
  const thenNode = layout.nodes.find((item) => item.id === 'then-step')!;
  const elseNode = layout.nodes.find((item) => item.id === 'else-step')!;
  const afterNode = layout.nodes.find((item) => item.id === 'after')!;

  assert.equal(frames.length, 2);
  assert.notEqual(thenNode.position.y, elseNode.position.y);
  assert.ok(afterNode.position.x > thenNode.position.x);
  assert.ok(afterNode.position.x > elseNode.position.x);
  assert.ok(layout.edges.some((edge) => edge.label === 'Đúng'));
  assert.ok(layout.edges.some((edge) => edge.label === 'Sai'));
});

test('ELK creates placeholders for empty scopes including random branches', async () => {
  const layout = await layoutScenarioAutomation([
    node('condition', 'a0', null, 'if_variable'),
    node('loop', 'a1', null, 'repeat'),
    node('random', 'a2', null, 'random_pick', {
      branch_weights: [2, 1]
    })
  ]);
  const placeholders = layout.nodes.filter(
    (item) => item.kind === 'placeholder'
  );

  assert.equal(placeholders.length, 5);
  assert.deepEqual(
    placeholders.map((item) => item.scope),
    [
      { parentId: 'condition', branch: 'then' },
      { parentId: 'condition', branch: 'else' },
      { parentId: 'loop', branch: 'steps' },
      { parentId: 'random', branch: 'branch_0' },
      { parentId: 'random', branch: 'branch_1' }
    ]
  );
});

test('layout remains valid after canonical cross-scope movement', async () => {
  const nodes = [
    node('move-me', 'a0'),
    node('condition', 'a1', null, 'if_element'),
    node('then-step', 'a0', { parentId: 'condition', branch: 'then' }),
    node('else-step', 'a0', { parentId: 'condition', branch: 'else' }),
    node('after', 'a2')
  ];
  const moved = moveScenarioNode(
    { nodes, edges: [] },
    'move-me',
    { parentId: 'condition', branch: 'else' },
    'else-step'
  );

  assert.ok(moved);
  const layout = await layoutScenarioAutomation(moved.nodes, moved.edges);
  const contentNodes = layout.nodes.filter(
    (item) => item.kind === 'step' || item.kind === 'anchor'
  );

  assert.ok(
    layout.nodes.some((item) => item.id === scenarioStepNodeId('move-me'))
  );
  assert.ok(layout.edges.every((edge) => edge.points.length >= 2));
  for (const item of contentNodes) {
    assert.ok(Number.isFinite(item.position.x));
    assert.ok(Number.isFinite(item.position.y));
  }
  for (let i = 0; i < contentNodes.length; i += 1) {
    for (let j = i + 1; j < contentNodes.length; j += 1) {
      const a = contentNodes[i];
      const b = contentNodes[j];
      const overlaps =
        a.position.x < b.position.x + b.width &&
        a.position.x + a.width > b.position.x &&
        a.position.y < b.position.y + b.height &&
        a.position.y + a.height > b.position.y;
      assert.equal(overlaps, false, `${a.id} overlaps ${b.id}`);
    }
  }
});

test('nested random and loop graph layouts have finite non-overlapping bounds', async () => {
  const nodes = [
    node('random', 'a0', null, 'random_pick', { branch_weights: [2, 1] }),
    node('loop', 'a0', { parentId: 'random', branch: 'branch_0' }, 'repeat'),
    node('wait', 'a0', { parentId: 'loop', branch: 'steps' }),
    node('tap', 'a1', { parentId: 'loop', branch: 'steps' }, 'tap_ratio'),
    node(
      'input',
      'a0',
      { parentId: 'random', branch: 'branch_1' },
      'input_text'
    )
  ];
  const layout = await layoutScenarioAutomation(nodes);
  const contentNodes = layout.nodes.filter(
    (item) => item.kind === 'step' || item.kind === 'anchor'
  );

  for (const item of contentNodes) {
    assert.ok(Number.isFinite(item.position.x));
    assert.ok(Number.isFinite(item.position.y));
    assert.ok(item.width > 0);
    assert.ok(item.height > 0);
  }

  for (let i = 0; i < contentNodes.length; i += 1) {
    for (let j = i + 1; j < contentNodes.length; j += 1) {
      const a = contentNodes[i];
      const b = contentNodes[j];
      const overlaps =
        a.position.x < b.position.x + b.width &&
        a.position.x + a.width > b.position.x &&
        a.position.y < b.position.y + b.height &&
        a.position.y + a.height > b.position.y;
      assert.equal(overlaps, false, `${a.id} overlaps ${b.id}`);
    }
  }
});
