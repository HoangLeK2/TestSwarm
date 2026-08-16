import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowStep } from '../../../campaigns/components/scenario-steps/types';
import {
  findStepByFlowgramId,
  patchStepByFlowgramId
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './patch-step-tree.ts';

const fbGroupLoop: FlowStep = {
  type: 'loop',
  count: 10,
  steps: [
    {
      type: 'social_open_comments',
      _fgId: 'tap-node',
      then: [
        {
          type: 'extract',
          entity: 'comments',
          platform: 'facebook',
          _fgId: 'extract-node',
          max_items: 500
        }
      ],
      else: []
    }
  ]
} as FlowStep;

test('patchStepByFlowgramId updates extract inside social_open_comments then branch', () => {
  const next = patchStepByFlowgramId([fbGroupLoop], 'extract-node', {
    type: 'extract',
    entity: 'comments',
    platform: 'facebook',
    max_items: 120,
    comment_scroll_passes: 12
  } as FlowStep);

  const loop = next[0] as FlowStep & { steps?: FlowStep[] };
  const tap = loop.steps?.[0] as FlowStep & { then?: FlowStep[] };
  const extract = tap.then?.[0] as FlowStep & { max_items?: number };

  assert.equal(extract.max_items, 120);
  assert.equal(extract.comment_scroll_passes, 12);
  assert.equal((extract as Record<string, unknown>)._fgId, 'extract-node');
});

test('findStepByFlowgramId locates nested extract under social_open_comments', () => {
  const found = findStepByFlowgramId([fbGroupLoop], 'extract-node');
  assert.ok(found);
  assert.equal(found.type, 'extract');
  assert.equal((found as { entity?: string }).entity, 'comments');
});

test('findStepByFlowgramId locates children under generic if step', () => {
  const steps: FlowStep[] = [
    {
      type: 'if',
      then: [{ type: 'tap_selector', _fgId: 'then-child', value: 'Follow' }],
      else: []
    }
  ];

  const found = findStepByFlowgramId(steps, 'then-child');

  assert.ok(found);
  assert.equal(found.type, 'tap_selector');
  assert.equal((found as { value?: string }).value, 'Follow');
});

test('patchStepByFlowgramId updates child under generic random branch', () => {
  const steps: FlowStep[] = [
    {
      type: 'random_pick',
      branches: [
        {
          weight: 2,
          steps: [{ type: 'wait', seconds: 1, _fgId: 'branch-child' }]
        }
      ]
    }
  ];

  const next = patchStepByFlowgramId(steps, 'branch-child', {
    type: 'wait',
    seconds: 5
  });
  const randomPick = next[0] as FlowStep & {
    branches?: Array<{ steps?: FlowStep[] }>;
  };
  const child = randomPick.branches?.[0]?.steps?.[0];

  assert.equal(child?.type, 'wait');
  assert.equal((child as { seconds?: number }).seconds, 5);
  assert.equal((child as Record<string, unknown>)._fgId, 'branch-child');
});
