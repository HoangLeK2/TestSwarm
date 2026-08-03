import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildHierarchyBackoffKey,
  buildHierarchyRequestKey,
  buildHierarchyUrl,
  HIERARCHY_REQUEST_TIMEOUT_MS,
  resolveHierarchyFetchPriority,
  shouldBackoffHierarchyError,
  shouldRespectHierarchyBackoff,
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

test('manual hierarchy refresh bypasses failure cooldown', () => {
  assert.equal(shouldRespectHierarchyBackoff(), true);
  assert.equal(shouldRespectHierarchyBackoff({}), true);
  assert.equal(shouldRespectHierarchyBackoff({ bypassBackoff: false }), true);
  assert.equal(shouldRespectHierarchyBackoff({ bypassBackoff: true }), false);
});

test('hierarchy request priority defaults to background', () => {
  assert.equal(resolveHierarchyFetchPriority(), 'background');
  assert.equal(resolveHierarchyFetchPriority({}), 'background');
  assert.equal(
    buildHierarchyUrl('serial 1', false),
    '/devices/serial%201/hierarchy'
  );
  assert.equal(
    buildHierarchyUrl('serial 1', true),
    '/devices/serial%201/hierarchy?refresh=1'
  );
});

test('visible hierarchy requests opt in explicitly', () => {
  assert.equal(
    resolveHierarchyFetchPriority({ priority: 'visible' }),
    'visible'
  );
  assert.equal(
    buildHierarchyUrl('serial 1', true, { priority: 'visible' }),
    '/devices/serial%201/hierarchy?refresh=1&priority=visible'
  );
});

test('hierarchy in-flight key separates visible and background lanes', () => {
  assert.notEqual(
    buildHierarchyRequestKey('abc', true, { priority: 'visible' }),
    buildHierarchyRequestKey('abc', true, { priority: 'background' })
  );
  assert.notEqual(
    buildHierarchyRequestKey('abc', true, { priority: 'visible' }),
    buildHierarchyRequestKey('abc', false, { priority: 'visible' })
  );
});

test('hierarchy backoff key separates priority but not refresh mode', () => {
  assert.equal(
    buildHierarchyBackoffKey('abc', { priority: 'background' }),
    buildHierarchyBackoffKey('abc', { priority: 'background' })
  );
  assert.notEqual(
    buildHierarchyBackoffKey('abc', { priority: 'visible' }),
    buildHierarchyBackoffKey('abc', { priority: 'background' })
  );
});
