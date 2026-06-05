import assert from 'node:assert/strict';
import test from 'node:test';

import {
  directObjectStorageUrl,
  isImageArtifact,
  resolveArtifactUrl,
  rewriteLegacyObjectStorageUrl,
  shouldProxyArtifactFetch
} from './artifact-url.ts';

test('rewriteLegacyObjectStorageUrl maps localhost MinIO to R2 public base', () => {
  const prev = process.env.NEXT_PUBLIC_OBJECT_STORAGE_PUBLIC_BASE_URL;
  process.env.NEXT_PUBLIC_OBJECT_STORAGE_PUBLIC_BASE_URL =
    'https://pub.example.r2.dev';
  try {
    const raw = 'http://localhost:9000/content-screenshots/abc123.jpg';
    assert.equal(
      rewriteLegacyObjectStorageUrl(raw),
      'https://pub.example.r2.dev/content-screenshots/abc123.jpg'
    );
    assert.equal(resolveArtifactUrl(raw), rewriteLegacyObjectStorageUrl(raw));
  } finally {
    if (prev === undefined) {
      delete process.env.NEXT_PUBLIC_OBJECT_STORAGE_PUBLIC_BASE_URL;
    } else {
      process.env.NEXT_PUBLIC_OBJECT_STORAGE_PUBLIC_BASE_URL = prev;
    }
  }
});

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

test('shouldProxyArtifactFetch is false for local MinIO public URL', () => {
  const raw =
    'http://localhost:9000/device-farm/content-screenshots/abc123.jpg';
  assert.equal(shouldProxyArtifactFetch(raw, raw), false);
  assert.equal(directObjectStorageUrl(raw, raw), raw);
});

test('shouldProxyArtifactFetch is true for execution artifact proxy path', () => {
  const raw = '/artifacts/81f9a485-43dd-41b7-8844-dc88cd10eed3/content';
  assert.equal(shouldProxyArtifactFetch(raw, null), true);
  assert.equal(directObjectStorageUrl(raw, null), null);
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
