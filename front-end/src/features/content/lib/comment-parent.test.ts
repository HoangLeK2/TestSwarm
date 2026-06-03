import assert from 'node:assert/strict';
import test from 'node:test';

import { commentParentSummary } from './comment-parent.ts';

test('commentParentSummary shows human-readable parent anchor', () => {
  const summary = commentParentSummary({
    parent_id: 'scoped-parent-hash',
    raw_data: {
      parent_post_id: 'pid-parent',
      parent_post_anchor: {
        author: 'Alice',
        timestamp: '1 giờ',
        text_prefix: 'Đây là nội dung bài viết gốc'
      }
    }
  });

  assert.deepEqual(summary, {
    primary: 'Alice · 1 giờ',
    secondary: 'Đây là nội dung bài viết gốc',
    postId: 'pid-parent'
  });
});

test('commentParentSummary falls back to parser post id', () => {
  const summary = commentParentSummary({
    parent_id: null,
    raw_data: { parent_post_id: 'ee5add7e48beb17f-extra' }
  });

  assert.equal(summary?.primary, 'Post ee5add7e48beb17…');
  assert.equal(summary?.secondary, null);
});
