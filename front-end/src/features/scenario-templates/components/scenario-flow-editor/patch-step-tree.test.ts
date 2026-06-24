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
      type: 'fb_tap_comment_button',
      _fgId: 'tap-node',
      then: [
        {
          type: 'extract',
          strategy: 'fb_comments',
          _fgId: 'extract-node',
          max_items: 500
        }
      ],
      else: []
    }
  ]
} as FlowStep;

test('patchStepByFlowgramId updates extract inside fb_tap_comment_button then branch', () => {
  const next = patchStepByFlowgramId([fbGroupLoop], 'extract-node', {
    type: 'extract',
    strategy: 'fb_comments',
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

test('findStepByFlowgramId locates nested extract under fb_tap_comment_button', () => {
  const found = findStepByFlowgramId([fbGroupLoop], 'extract-node');
  assert.ok(found);
  assert.equal(found.type, 'extract');
  assert.equal((found as { strategy?: string }).strategy, 'fb_comments');
});
