import assert from 'node:assert/strict';
import test from 'node:test';

import {
  dedupeLinkPreviewNoise,
  resolveCommentDisplayBody,
  shouldHideParentSecondary
} from './comment-display.ts';

test('shouldHideParentSecondary detects duplicate parent and comment text', () => {
  const text = 'Same comment text';
  assert.equal(shouldHideParentSecondary(text, text), true);
  assert.equal(shouldHideParentSecondary('prefix ' + text, text), true);
});

test('dedupeLinkPreviewNoise collapses repeated domains', () => {
  assert.equal(
    dedupeLinkPreviewNoise(
      'Liên kết được chia sẻ: vilao.ai, vilao.ai vilao.ai vilao.ai'
    ),
    'Liên kết được chia sẻ: vilao.ai'
  );
});

test('resolveCommentDisplayBody prefers body over raw text', () => {
  assert.equal(
    resolveCommentDisplayBody({
      body: 'from body',
      title: null,
      raw_data: { text: 'from raw' }
    }),
    'from body'
  );
});
