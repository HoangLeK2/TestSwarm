import assert from 'node:assert/strict';
import test from 'node:test';

import { createFollowerH264SlotPool } from './follower-h264-slots';

test('caps concurrent follower H264 previews', () => {
  const pool = createFollowerH264SlotPool(2);
  const releaseFirst = pool.acquire();
  const releaseSecond = pool.acquire();

  assert.equal(typeof releaseFirst, 'function');
  assert.equal(typeof releaseSecond, 'function');
  assert.equal(pool.getActiveCount(), 2);
  assert.equal(pool.acquire(), null);
});

test('releases a slot once and wakes waiting previews', () => {
  const pool = createFollowerH264SlotPool(1);
  const release = pool.acquire();
  let changes = 0;
  const unsubscribe = pool.subscribe(() => {
    changes += 1;
  });

  assert.ok(release);
  release();
  release();

  assert.equal(pool.getActiveCount(), 0);
  assert.equal(changes, 1);
  assert.equal(typeof pool.acquire(), 'function');
  unsubscribe();
});
