import assert from 'node:assert/strict';
import test from 'node:test';

import { isImageArtifact, resolveArtifactUrl } from './artifact-url.ts';

test('resolveArtifactUrl prefixes relative captures path', () => {
  const out = resolveArtifactUrl('/captures/screenshots/a.jpg');
  assert.ok(out?.includes('/captures/screenshots/a.jpg'));
});

test('isImageArtifact detects by kind and extension', () => {
  assert.equal(isImageArtifact('image', null), true);
  assert.equal(isImageArtifact('text', 'https://x.test/a.png'), true);
  assert.equal(isImageArtifact('text', 'https://x.test/a.xml'), false);
});
