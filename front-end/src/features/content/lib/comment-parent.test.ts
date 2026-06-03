import assert from 'node:assert/strict';
import test from 'node:test';

import { commentParentSummary } from './comment-parent.ts';

test('commentParentSummary shows human-readable parent anchor', () => {
  const summary = commentParentSummary({
    parent_id: 'scoped-parent-hash',
    raw_data: {
      parent_post_id: 'pid-parent',
      parent_context_source: 'post_detail',
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
    postId: 'pid-parent',
    linkedParentId: 'scoped-parent-hash',
    source: 'post_detail'
  });
});

test('commentParentSummary falls back to parser post id', () => {
  const summary = commentParentSummary({
    parent_id: null,
    raw_data: { parent_post_id: 'ee5add7e48beb17f-extra' }
  });

  assert.equal(summary?.primary, 'Post ee5add7e48beb17…');
  assert.equal(summary?.secondary, null);
  assert.equal(summary?.linkedParentId, null);
  assert.equal(summary?.source, null);
});

test('commentParentSummary can identify a linked parent from hash only', () => {
  const summary = commentParentSummary({
    parent_id: 'scoped-parent-hash',
    raw_data: {}
  });

  assert.equal(summary?.primary, 'Bài gốc đã liên kết');
  assert.equal(summary?.secondary, 'scoped-parent-h…');
  assert.equal(summary?.linkedParentId, 'scoped-parent-hash');
});

test('commentParentSummary prefers resolved parent item over stale parent id', () => {
  const summary = commentParentSummary({
    parent_id: 'stale-target-hash',
    parent_item_hash: 'real-post-hash',
    parent_item_author: 'Alice',
    parent_item_body: 'Nội dung bài viết cha đã resolve từ DB',
    raw_data: {
      parent_post_anchor: {
        post_key: 'post-key-1',
        text_prefix: 'fallback text'
      }
    }
  });

  assert.equal(summary?.primary, 'Alice');
  assert.equal(summary?.secondary, 'Nội dung bài viết cha đã resolve từ DB');
  assert.equal(summary?.linkedParentId, 'real-post-hash');
  assert.equal(summary?.postId, 'post-key-1');
});
