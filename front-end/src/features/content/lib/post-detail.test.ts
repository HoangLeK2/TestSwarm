import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldShowPostComments } from './post-detail.ts';

test('shouldShowPostComments for platform_items collection', () => {
  assert.equal(
    shouldShowPostComments({
      item_level: 0,
      content_type: 'ig_media',
      collection: 'platform_items'
    }),
    true
  );
});

test('shouldShowPostComments false for comments', () => {
  assert.equal(
    shouldShowPostComments({
      item_level: 1,
      content_type: 'ig_comment',
      collection: 'platform_items'
    }),
    false
  );
});
