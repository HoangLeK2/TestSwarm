import assert from 'node:assert/strict';
import test from 'node:test';

import {
  directObjectStorageUrl,
  isImageArtifact,
  resolveArtifactUrl,
  shouldProxyArtifactFetch
} from './artifact-url.ts';

test('resolveArtifactUrl prefixes relative captures path', () => {
  const out = resolveArtifactUrl('/captures/screenshots/a.jpg');
  assert.ok(out?.includes('/captures/screenshots/a.jpg'));
});

test('isImageArtifact detects by kind and extension', () => {
  assert.equal(isImageArtifact('image', null), true);
  assert.equal(isImageArtifact('text', 'https://x.test/a.png'), true);
  assert.equal(isImageArtifact('text', 'https://x.test/a.xml'), false);
});

test('shouldProxyArtifactFetch is false for absolute R2 URLs', () => {
  const raw =
    'https://pub.example.r2.dev/device-farm/content-screenshots/abc.jpg';
  assert.equal(shouldProxyArtifactFetch(raw, raw), false);
  assert.equal(directObjectStorageUrl(raw, raw), raw);
});

test('shouldProxyArtifactFetch is true for local screenshot paths', () => {
  const raw = 'screenshots/deadbeef.jpg';
  const resolved = resolveArtifactUrl(raw, 'http://localhost:8081');
  assert.equal(shouldProxyArtifactFetch(raw, resolved), true);
  assert.equal(directObjectStorageUrl(raw, resolved), null);
});

test('isImageArtifact detects proxy screenshots without file extension', () => {
  assert.equal(
    isImageArtifact('text', '/artifacts/abc/content', {
      label: 'Post · Screenshot'
    }),
    true
  );
  assert.equal(
    isImageArtifact('text', '/artifacts/abc/content', {
      mimeType: 'image/png'
    }),
    true
  );
  assert.equal(
    isImageArtifact('text', '/artifacts/abc/content', {
      label: 'Post · Hierarchy'
    }),
    false
  );
});
