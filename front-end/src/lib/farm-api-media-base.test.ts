import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveDeviceFarmMediaBaseForOrigin } from './farm-api';

test('resolveDeviceFarmMediaBaseForOrigin uses /api for same-origin production proxy', () => {
  assert.equal(
    resolveDeviceFarmMediaBaseForOrigin(
      'https://device-farm.tommadethis.app',
      'https://device-farm.tommadethis.app'
    ),
    'https://device-farm.tommadethis.app/api'
  );
});

test('resolveDeviceFarmMediaBaseForOrigin uses /api when public API env is empty in browser', () => {
  assert.equal(
    resolveDeviceFarmMediaBaseForOrigin(
      '',
      'https://device-farm.tommadethis.app'
    ),
    '/api'
  );
});

test('resolveDeviceFarmMediaBaseForOrigin appends /api for direct backend origins', () => {
  assert.equal(
    resolveDeviceFarmMediaBaseForOrigin(
      'https://farm-api.example.com',
      'https://device-farm.tommadethis.app'
    ),
    'https://farm-api.example.com/api'
  );
});

test('resolveDeviceFarmMediaBaseForOrigin maps localhost frontend port to backend /api', () => {
  assert.equal(
    resolveDeviceFarmMediaBaseForOrigin(
      'http://localhost:3000',
      'http://localhost:3000'
    ),
    'http://localhost:8081/api'
  );
});

test('resolveDeviceFarmMediaBaseForOrigin does not double an existing /api suffix', () => {
  assert.equal(
    resolveDeviceFarmMediaBaseForOrigin(
      'https://device-farm.tommadethis.app/api',
      'https://device-farm.tommadethis.app'
    ),
    'https://device-farm.tommadethis.app/api'
  );
});
