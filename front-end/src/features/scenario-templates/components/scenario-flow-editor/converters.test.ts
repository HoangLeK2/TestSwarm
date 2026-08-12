import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowStep } from '../../../campaigns/components/scenario-steps/types';
import {
  flowDocToSteps,
  stepToFlowNode,
  stepsToFlowDoc
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './converters.ts';

test('Flowgram converter preserves generic if then/else children', () => {
  const steps: FlowStep[] = [
    {
      type: 'if',
      condition: { element_exists: { by: 'text', value: 'Follow' } },
      then: [{ type: 'tap_selector', by: 'text', value: 'Follow' }],
      else: [{ type: 'wait', seconds: 1 }]
    }
  ];

  const roundTrip = flowDocToSteps(stepsToFlowDoc(steps));
  const condition = roundTrip[0] as FlowStep & {
    then?: FlowStep[];
    else?: FlowStep[];
  };

  assert.equal(condition.type, 'if');
  assert.equal(condition.then?.length, 1);
  assert.equal(condition.then?.[0]?.type, 'tap_selector');
  assert.equal(condition.else?.length, 1);
  assert.equal(condition.else?.[0]?.type, 'wait');
});

test('Flowgram converter preserves random_pick children when only one branch exists', () => {
  const steps: FlowStep[] = [
    {
      type: 'random_pick',
      branches: [
        {
          weight: 3,
          steps: [{ type: 'tap_selector', by: 'text', value: 'Like' }]
        }
      ]
    }
  ];

  const roundTrip = flowDocToSteps(stepsToFlowDoc(steps));
  const randomPick = roundTrip[0] as FlowStep & {
    branches?: Array<{ weight?: number; steps?: FlowStep[] }>;
  };

  assert.equal(randomPick.type, 'random_pick');
  assert.equal(randomPick.branches?.length, 1);
  assert.equal(randomPick.branches?.[0]?.weight, 3);
  assert.equal(randomPick.branches?.[0]?.steps?.length, 1);
  assert.equal(randomPick.branches?.[0]?.steps?.[0]?.type, 'tap_selector');
});

test('stepToFlowNode creates visible control blocks for plus-menu flow nodes', () => {
  const ifNode = stepToFlowNode({
    type: 'if_element',
    by: 'text',
    value: 'Follow',
    then: [],
    else: []
  });
  const repeatNode = stepToFlowNode({
    type: 'repeat',
    count: 2,
    steps: []
  });

  assert.equal(ifNode.type, 'condition');
  assert.equal(ifNode.blocks?.length, 2);
  assert.equal(ifNode.blocks?.[0]?.data?.title, 'Nếu đúng (then)');
  assert.equal(repeatNode.type, 'loop_node');
  assert.deepEqual(repeatNode.blocks, []);
});

test('Flowgram document uses canonical IDs for nested scenario nodes', () => {
  const steps: FlowStep[] = [
    {
      id: 'condition-id',
      order: 'a0',
      type: 'if_element',
      then: [
        {
          id: 'loop-id',
          order: 'a0',
          type: 'repeat',
          count: 2,
          steps: [{ id: 'wait-id', order: 'a0', type: 'wait', seconds: 1 }]
        }
      ],
      else: [{ id: 'else-id', order: 'a0', type: 'wait', seconds: 1 }]
    }
  ];

  const doc = stepsToFlowDoc(steps);
  const condition = doc.nodes.find((node) => node.id === 'condition-id');
  const loop = condition?.blocks?.[0]?.blocks?.find(
    (node) => node.id === 'loop-id'
  );

  assert.ok(condition);
  assert.equal(condition.blocks?.[0]?.id, 'condition-id_then');
  assert.equal(condition.blocks?.[1]?.id, 'condition-id_else');
  assert.ok(loop);
  assert.equal(loop.blocks?.[0]?.id, 'wait-id');
});

test('Flowgram reorder preserves canonical IDs and regenerates sibling order', () => {
  const doc = stepsToFlowDoc([
    { id: 'first', order: 'a0', type: 'wait', seconds: 1 },
    { id: 'second', order: 'a1', type: 'wait', seconds: 2 }
  ]);
  const firstIndex = doc.nodes.findIndex((node) => node.id === 'first');
  const secondIndex = doc.nodes.findIndex((node) => node.id === 'second');
  const [second] = doc.nodes.splice(secondIndex, 1);
  doc.nodes.splice(firstIndex, 0, second!);

  const roundTrip = flowDocToSteps(doc);

  assert.deepEqual(
    roundTrip.map((step) => step.id),
    ['second', 'first']
  );
  assert.deepEqual(
    roundTrip.map((step) => step._fgId),
    ['second', 'first']
  );
  assert.ok(roundTrip[0]!.order < roundTrip[1]!.order);
});

test('Flowgram round trip preserves explicit empty random branches and weights', () => {
  const doc = stepsToFlowDoc([
    {
      id: 'random-id',
      order: 'a0',
      type: 'random_pick',
      branches: [
        { weight: 3, steps: [] },
        {
          weight: 1,
          steps: [{ id: 'branch-child', order: 'a0', type: 'wait', seconds: 1 }]
        }
      ]
    }
  ]);
  const random = doc.nodes.find((node) => node.id === 'random-id');
  const roundTrip = flowDocToSteps(doc);

  assert.deepEqual(
    random?.blocks?.map((block) => block.id),
    ['random-id_branch_0', 'random-id_branch_1']
  );
  assert.deepEqual(
    roundTrip[0]?.branches.map(
      (branch: { weight: number; steps: FlowStep[] }) => ({
        weight: branch.weight,
        ids: branch.steps.map((step) => step.id)
      })
    ),
    [
      { weight: 3, ids: [] },
      { weight: 1, ids: ['branch-child'] }
    ]
  );
});

test('legacy steps without canonical IDs retain their Flowgram identity', () => {
  const roundTrip = flowDocToSteps(
    stepsToFlowDoc([{ type: 'wait', seconds: 1, _fgId: 'legacy-id' }])
  );

  assert.equal(roundTrip[0]?.id, 'legacy-id');
  assert.equal(roundTrip[0]?._fgId, 'legacy-id');
});
