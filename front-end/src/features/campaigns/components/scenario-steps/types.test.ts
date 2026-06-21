import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createDefaultStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './types.ts';

test('default fb comment extract uses balanced fast crawl budget', () => {
  const step = createDefaultStep('extract_fb_comments');

  assert.equal(step.max_items, 220);
  assert.equal(step.comment_scroll_passes, 16);
  assert.equal(step.comment_swipes_per_dump, 4);
  assert.equal(step.comment_max_snapshots, 12);
  assert.equal(step.comment_scroll_wall_s, 25);
  assert.equal(step.comment_stop_if_no_new, true);
  assert.equal(step.stop_if_no_new, true);
});

test('custom fb comment crawl budget survives frontend JSON payload', () => {
  const step = {
    ...createDefaultStep('extract_fb_comments'),
    max_items: 333,
    comment_scroll_passes: 27,
    comment_swipes_per_dump: 5,
    comment_max_snapshots: 18,
    comment_scroll_wall_s: 44,
    comment_stop_if_no_new: false,
    stop_if_no_new: false,
    no_new_threshold: 6
  };

  const payload = JSON.parse(JSON.stringify(step));

  assert.equal(payload.max_items, 333);
  assert.equal(payload.comment_scroll_passes, 27);
  assert.equal(payload.comment_swipes_per_dump, 5);
  assert.equal(payload.comment_max_snapshots, 18);
  assert.equal(payload.comment_scroll_wall_s, 44);
  assert.equal(payload.comment_stop_if_no_new, false);
  assert.equal(payload.stop_if_no_new, false);
  assert.equal(payload.no_new_threshold, 6);
});
