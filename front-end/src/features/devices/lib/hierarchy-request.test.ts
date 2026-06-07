import assert from 'node:assert/strict';
import test from 'node:test';

import {
  HIERARCHY_REQUEST_TIMEOUT_MS,
  shouldBackoffHierarchyError
} from './hierarchy-request.ts';

test('shouldBackoffHierarchyError backs off unavailable hierarchy endpoint', () => {
  assert.equal(
    shouldBackoffHierarchyError({ response: { status: 503 } }),
    true
  );
});

test('shouldBackoffHierarchyError backs off request timeouts', () => {
  assert.equal(shouldBackoffHierarchyError({ code: 'ECONNABORTED' }), true);
  assert.equal(shouldBackoffHierarchyError({ code: 'ETIMEDOUT' }), true);
});

test('hierarchy request timeout is bounded for UI responsiveness', () => {
  assert.equal(HIERARCHY_REQUEST_TIMEOUT_MS <= 5000, true);
});
