import assert from 'node:assert/strict';
import test from 'node:test';

import {
  HIERARCHY_REQUEST_TIMEOUT_MS,
  shouldBackoffHierarchyError,
  shouldReuseHierarchyInFlight
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

test('interaction hierarchy requests bypass in-flight auto refresh requests', () => {
  assert.equal(shouldReuseHierarchyInFlight(), true);
  assert.equal(shouldReuseHierarchyInFlight({}), true);
  assert.equal(shouldReuseHierarchyInFlight({ bypassInFlight: false }), true);
  assert.equal(shouldReuseHierarchyInFlight({ bypassInFlight: true }), false);
});
