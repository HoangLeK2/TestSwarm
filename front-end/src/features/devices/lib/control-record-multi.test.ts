import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getActiveMultiSerials,
  getRenderSafeFollowerSerials,
  resetFollowersAfterPrimaryChange,
  sanitizeMultiFollowerSerials
} from './control-record-multi.ts';

test('resetFollowersAfterPrimaryChange clears followers when primary changes', () => {
  assert.deepEqual(
    resetFollowersAfterPrimaryChange('phone-A', 'phone-B', ['phone-B']),
    []
  );
  assert.deepEqual(
    resetFollowersAfterPrimaryChange(null, 'phone-A', ['phone-B']),
    ['phone-B']
  );
  assert.deepEqual(
    resetFollowersAfterPrimaryChange('phone-A', 'phone-A', ['phone-B']),
    ['phone-B']
  );
});

test('sanitizeMultiFollowerSerials keeps only eligible followers within limit', () => {
  assert.deepEqual(
    sanitizeMultiFollowerSerials(
      ['phone-B', 'offline-phone', 'phone-C'],
      ['phone-B', 'phone-C'],
      1
    ),
    ['phone-B']
  );
});

test('getActiveMultiSerials prepends primary and removes duplicate follower', () => {
  assert.deepEqual(getActiveMultiSerials('phone-A', ['phone-A', 'phone-B']), [
    'phone-A',
    'phone-B'
  ]);
  assert.deepEqual(getActiveMultiSerials(null, ['phone-B']), []);
});

test('getRenderSafeFollowerSerials hides stale followers during primary switch render', () => {
  assert.deepEqual(
    getRenderSafeFollowerSerials('phone-A', 'phone-B', ['phone-B']),
    []
  );
  assert.deepEqual(
    getRenderSafeFollowerSerials('phone-A', 'phone-A', ['phone-B']),
    ['phone-B']
  );
});
