import assert from 'node:assert/strict';
import test from 'node:test';
import { boundedInt } from './follower-preview-timing';

test('boundedInt uses fallback for missing or invalid values', () => {
  assert.equal(boundedInt(undefined, 750, 0, 5_000), 750);
  assert.equal(boundedInt('bad', 750, 0, 5_000), 750);
});

test('boundedInt clamps configured values', () => {
  assert.equal(boundedInt('-1', 750, 0, 5_000), 0);
  assert.equal(boundedInt('9000', 750, 0, 5_000), 5_000);
  assert.equal(boundedInt('1200.6', 750, 0, 5_000), 1_201);
});
