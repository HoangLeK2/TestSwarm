import assert from 'node:assert/strict';
import test from 'node:test';

import type { DragEndEvent } from '@dnd-kit/core';
import type { FlowStep } from '../scenario-steps/types';
import { encodeFlowListRef } from './flow-dnd-ids';
import {
  applyFlowDragEnd
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './flow-tree-dnd.ts';

function eventFor({
  activeId,
  activeContainer,
  overId,
  overContainer,
  overContainerDataKey = 'sortable'
}: {
  activeId: string;
  activeContainer: string;
  overId: string;
  overContainer: string;
  overContainerDataKey?: 'sortable' | 'flowListContainerId';
}): DragEndEvent {
  return {
    active: {
      id: activeId,
      data: { current: { sortable: { containerId: activeContainer } } }
    },
    over: {
      id: overId,
      data: {
        current:
          overContainerDataKey === 'sortable'
            ? { sortable: { containerId: overContainer } }
            : { flowListContainerId: overContainer }
      }
    }
  } as DragEndEvent;
}

test('applyFlowDragEnd moves a preceding root step into an if branch', () => {
  const rootContainer = encodeFlowListRef({ kind: 'root' });
  const thenContainer = encodeFlowListRef({
    kind: 'nested',
    rootIndex: 1,
    pathToBracket: [],
    listKey: 'then'
  });
  const steps: FlowStep[] = [
    { _id: 'drag', type: 'input_text', text: '${GROUP_NAME}' } as FlowStep,
    {
      _id: 'if',
      type: 'if_element',
      description: 'Tim kiem',
      then: [
        { _id: 'target', type: 'tap', by: 'description', value: 'Tim kiem' }
      ],
      else: []
    } as FlowStep,
    { _id: 'after', type: 'key', key: 'enter' } as FlowStep
  ];

  let next: FlowStep[] | null = null;
  applyFlowDragEnd(
    eventFor({
      activeId: 'drag',
      activeContainer: rootContainer,
      overId: 'target',
      overContainer: thenContainer
    }),
    steps,
    (value) => {
      next = value;
    }
  );

  assert.ok(next);
  assert.equal(next.length, 2);
  assert.equal(next[0]?._id, 'if');
  assert.deepEqual(
    ((next[0] as FlowStep & { then?: FlowStep[] }).then ?? []).map(
      (step) => step._id
    ),
    ['drag', 'target']
  );
  assert.equal(next[1]?._id, 'after');
});

test('applyFlowDragEnd appends into an empty if branch droppable lane', () => {
  const rootContainer = encodeFlowListRef({ kind: 'root' });
  const elseContainer = encodeFlowListRef({
    kind: 'nested',
    rootIndex: 1,
    pathToBracket: [],
    listKey: 'else'
  });
  const steps: FlowStep[] = [
    { _id: 'drag', type: 'key', key: 'enter' } as FlowStep,
    {
      _id: 'if',
      type: 'if_element',
      description: 'Tim kiem',
      then: [
        { _id: 'target', type: 'tap', by: 'description', value: 'Tim kiem' }
      ],
      else: []
    } as FlowStep
  ];

  let next: FlowStep[] | null = null;
  applyFlowDragEnd(
    eventFor({
      activeId: 'drag',
      activeContainer: rootContainer,
      overId: elseContainer,
      overContainer: elseContainer,
      overContainerDataKey: 'flowListContainerId'
    }),
    steps,
    (value) => {
      next = value;
    }
  );

  assert.ok(next);
  assert.equal(next.length, 1);
  assert.deepEqual(
    ((next[0] as FlowStep & { else?: FlowStep[] }).else ?? []).map(
      (step) => step._id
    ),
    ['drag']
  );
});

test('applyFlowDragEnd moves a preceding root step into a loop body', () => {
  const rootContainer = encodeFlowListRef({ kind: 'root' });
  const loopContainer = encodeFlowListRef({
    kind: 'nested',
    rootIndex: 1,
    pathToBracket: [],
    listKey: 'steps'
  });
  const steps: FlowStep[] = [
    { _id: 'drag', type: 'tap_ratio', x: 0.87, y: 0.04 } as FlowStep,
    {
      _id: 'loop',
      type: 'loop',
      count: 3,
      steps: [{ _id: 'target', type: 'wait', seconds: 0.5 }]
    } as FlowStep,
    { _id: 'after', type: 'key', key: 'enter' } as FlowStep
  ];

  let next: FlowStep[] | null = null;
  applyFlowDragEnd(
    eventFor({
      activeId: 'drag',
      activeContainer: rootContainer,
      overId: 'target',
      overContainer: loopContainer
    }),
    steps,
    (value) => {
      next = value;
    }
  );

  assert.ok(next);
  assert.equal(next.length, 2);
  assert.equal(next[0]?._id, 'loop');
  assert.deepEqual(
    ((next[0] as FlowStep & { steps?: FlowStep[] }).steps ?? []).map(
      (step) => step._id
    ),
    ['drag', 'target']
  );
  assert.equal(next[1]?._id, 'after');
});
