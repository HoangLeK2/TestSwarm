import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getFollowerGridColumnCount,
  getFollowerGridRowBounds,
  getFollowerGridRowCount
} from './follower-virtual-grid';

test('fits follower columns to the available width with a four-column cap', () => {
  assert.equal(getFollowerGridColumnCount(119, 19, 120), 1);
  assert.equal(getFollowerGridColumnCount(248, 19, 120), 2);
  assert.equal(getFollowerGridColumnCount(760, 19, 120), 4);
});

test('never creates more follower columns than devices', () => {
  assert.equal(getFollowerGridColumnCount(760, 2, 120), 2);
  assert.equal(getFollowerGridColumnCount(760, 0, 120), 1);
});

test('maps virtual rows to bounded follower slices', () => {
  assert.equal(getFollowerGridRowCount(19, 4), 5);
  assert.deepEqual(getFollowerGridRowBounds(0, 4, 19), {
    start: 0,
    end: 4
  });
  assert.deepEqual(getFollowerGridRowBounds(4, 4, 19), {
    start: 16,
    end: 19
  });
});
