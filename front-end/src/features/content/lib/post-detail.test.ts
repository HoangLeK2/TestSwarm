import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldShowPostComments } from './post-detail.ts';

test('shouldShowPostComments for fb_group_posts collection', () => {
  assert.equal(
    shouldShowPostComments({
      item_level: 0,
      content_type: 'fb_post',
      collection: 'fb_group_posts'
    }),
    true
  );
});

test('shouldShowPostComments false for comments', () => {
  assert.equal(
    shouldShowPostComments({
      item_level: 1,
      content_type: 'fb_comment',
      collection: 'fb_group_posts'
    }),
    false
  );
});
