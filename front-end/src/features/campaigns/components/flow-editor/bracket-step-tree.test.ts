import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowStep } from '../scenario-steps/types';
import {
  applyChildStepEdit,
  getChildStep,
  updateChildInStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './bracket-step-tree.ts';

const fbTapWithExtract: FlowStep = {
  type: 'social_open_comments',
  timeout: 6,
  then: [
    {
      type: 'extract',
      entity: 'comments',
      platform: 'facebook',
      max_items: 500,
      comment_scroll_passes: 48
    },
    { type: 'key', key: 'back' }
  ],
  else: [{ type: 'wait', seconds: 0.5 }]
};

test('getChildStep reads extract step from social_open_comments then branch', () => {
  const child = getChildStep(fbTapWithExtract, 'then', 0);
  assert.ok(child);
  assert.equal(child.type, 'extract');
  assert.equal(child.entity, 'comments');
  assert.equal(child.max_items, 500);
});

test('getChildStep reads else branch step', () => {
  const child = getChildStep(fbTapWithExtract, 'else', 0);
  assert.ok(child);
  assert.equal(child.type, 'wait');
});

test('updateChildInStep persists extract field edits inside then branch', () => {
  const extract = getChildStep(fbTapWithExtract, 'then', 0)!;
  const edited = {
    ...extract,
    max_items: 120,
    comment_scroll_passes: 12
  } as FlowStep;

  const next = updateChildInStep(fbTapWithExtract, 'then', 0, edited);
  const updated = getChildStep(next, 'then', 0);

  assert.ok(updated);
  assert.equal(updated.max_items, 120);
  assert.equal(updated.comment_scroll_passes, 12);
  assert.equal(getChildStep(next, 'then', 1)?.type, 'key');
});

test('applyChildStepEdit returns null when path is missing', () => {
  const extract = getChildStep(fbTapWithExtract, 'then', 0)!;
  assert.equal(applyChildStepEdit(fbTapWithExtract, null, extract), null);
  assert.equal(applyChildStepEdit(fbTapWithExtract, undefined, extract), null);
});

test('applyChildStepEdit uses latest parent snapshot for nested edits', () => {
  const parent: FlowStep = {
    ...fbTapWithExtract,
    timeout: 8
  };
  const extract = getChildStep(parent, 'then', 0)!;
  const edited = { ...extract, max_items: 42 } as FlowStep;

  const next = applyChildStepEdit(parent, { listKey: 'then', ci: 0 }, edited);
  assert.ok(next);
  assert.equal(next.timeout, 8);
  assert.equal(getChildStep(next, 'then', 0)?.max_items, 42);
});
