import assert from 'node:assert/strict';
import test from 'node:test';

import {
  analyzeStepTree,
  insertLocationForChildList,
  insertLocationFromPath,
  stepTreePathKey
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-tree-intelligence.ts';
import type { FlowStep } from '../components/scenario-steps/types.ts';

test('analyzeStepTree describes sequence nodes and nested control containers', () => {
  const steps = [
    {
      type: 'if_variable',
      name: 'HAS_TARGET',
      then: [{ type: 'tap_ratio', x: 0.5, y: 0.5 }],
      else: []
    },
    {
      type: 'loop',
      count: 2,
      steps: [{ type: 'wait', seconds: 1 }]
    },
    {
      type: 'random_pick',
      branches: [
        { steps: [{ type: 'input_text', text: 'hello' }] },
        { steps: [] }
      ]
    }
  ] as FlowStep[];

  const nodes = analyzeStepTree(steps);

  assert.deepEqual(
    nodes.map((node) => ({
      type: node.step.type,
      key: stepTreePathKey(node.path),
      kind: node.nodeKind,
      container: node.containerKey,
      parent: node.parentType
    })),
    [
      {
        type: 'if_variable',
        key: 'steps:0',
        kind: 'control',
        container: 'steps',
        parent: undefined
      },
      {
        type: 'tap_ratio',
        key: 'steps:0/then:0',
        kind: 'runnable',
        container: 'then',
        parent: 'if_variable'
      },
      {
        type: 'loop',
        key: 'steps:1',
        kind: 'control',
        container: 'steps',
        parent: undefined
      },
      {
        type: 'wait',
        key: 'steps:1/steps:0',
        kind: 'runnable',
        container: 'steps',
        parent: 'loop'
      },
      {
        type: 'random_pick',
        key: 'steps:2',
        kind: 'control',
        container: 'steps',
        parent: undefined
      },
      {
        type: 'input_text',
        key: 'steps:2/branches.0:0',
        kind: 'runnable',
        container: 'branches.0',
        parent: 'random_pick'
      }
    ]
  );

  const ifNode = nodes[0]!;
  assert.deepEqual(
    ifNode.childInsertLocations.map((location) => location.kind),
    ['then', 'else']
  );
  assert.equal(ifNode.insertBefore.kind, 'root');
  assert.equal(ifNode.insertAfter.insertIndex, 1);
});

test('analyzeStepTree keeps empty containers classified as control nodes', () => {
  const nodes = analyzeStepTree([
    { type: 'random_pick', branches: [] }
  ] as FlowStep[]);

  assert.equal(nodes[0]?.nodeKind, 'control');
  assert.equal(nodes[0]?.childInsertLocations.length, 0);
});

test('insert location labels root, branch, loop, and random branch contexts', () => {
  assert.deepEqual(insertLocationFromPath([{ listKey: 'steps', ci: 0 }]), {
    path: [{ listKey: 'steps', ci: 0 }],
    containerKey: 'steps',
    insertIndex: 0,
    depth: 0,
    kind: 'root',
    labelKey: 'rootSequence'
  });

  assert.equal(
    insertLocationFromPath([
      { listKey: 'steps', ci: 0 },
      { listKey: 'then', ci: 1 }
    ]).labelKey,
    'thenBranch'
  );
  assert.equal(
    insertLocationFromPath([
      { listKey: 'steps', ci: 0 },
      { listKey: 'else', ci: 0 }
    ]).kind,
    'else'
  );
  assert.equal(
    insertLocationFromPath([
      { listKey: 'steps', ci: 1 },
      { listKey: 'steps', ci: 2 }
    ]).labelKey,
    'loopBody'
  );
  assert.deepEqual(
    insertLocationFromPath([
      { listKey: 'steps', ci: 2 },
      { listKey: 'branches.1', ci: 0 }
    ]),
    {
      path: [
        { listKey: 'steps', ci: 2 },
        { listKey: 'branches.1', ci: 0 }
      ],
      containerKey: 'branches.1',
      insertIndex: 0,
      depth: 1,
      kind: 'random_branch',
      labelKey: 'randomBranch',
      labelValues: { number: 2 }
    }
  );
});

test('insertLocationForChildList converts editor child paths to step-tree paths', () => {
  const location = insertLocationForChildList(
    [{ listKey: 'then', childIndex: 0 }],
    'else',
    2
  );

  assert.deepEqual(location.path, [
    { listKey: 'then', ci: 0 },
    { listKey: 'else', ci: 2 }
  ]);
  assert.equal(location.kind, 'else');
  assert.equal(location.insertIndex, 2);
});
