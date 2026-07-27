import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldRunEmbedStream } from './embed-stream-visibility';

test('interactive embeds stay live outside the viewport', () => {
  assert.equal(
    shouldRunEmbedStream({ readOnlyPreview: false, nearViewport: false }),
    true
  );
});

test('read-only embeds pause outside the viewport', () => {
  assert.equal(
    shouldRunEmbedStream({ readOnlyPreview: true, nearViewport: false }),
    false
  );
});

test('read-only embeds resume near the viewport', () => {
  assert.equal(
    shouldRunEmbedStream({ readOnlyPreview: true, nearViewport: true }),
    true
  );
});
