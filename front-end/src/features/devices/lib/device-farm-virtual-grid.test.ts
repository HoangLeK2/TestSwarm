import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getDeviceGridColumnCount,
  getDeviceGridRenderMode,
  getDeviceGridRowBounds,
  getDeviceGridRowCount
} from './device-farm-virtual-grid';

test('derives responsive columns from the existing tile width and gap', () => {
  assert.equal(getDeviceGridColumnCount(279, 10), 1);
  assert.equal(getDeviceGridColumnCount(575, 10), 1);
  assert.equal(getDeviceGridColumnCount(592, 10), 2);
  assert.equal(getDeviceGridColumnCount(1_168, 10), 3);
  assert.equal(getDeviceGridColumnCount(1_200, 10), 4);
});

test('never creates more columns than devices', () => {
  assert.equal(getDeviceGridColumnCount(1_500, 2), 2);
  assert.equal(getDeviceGridColumnCount(1_500, 0), 1);
});

test('device count is not a proxy for the grid being mounted', () => {
  // The exact sequence that painted an empty grid under a "1/1" header: a
  // WebSocket status frame populates the device list while the first
  // /api/devices/live call is still in flight, so the counts reach their final
  // value one render BEFORE the grid mounts. Anything that wires up grid
  // measurement must key off the mounted node, not off these numbers.
  const counts = { deviceCount: 1, filteredCount: 1 };

  assert.equal(
    getDeviceGridRenderMode({
      isInitialError: false,
      isInitialLoading: true,
      ...counts
    }),
    'loading'
  );
  assert.equal(
    getDeviceGridRenderMode({
      isInitialError: false,
      isInitialLoading: false,
      ...counts
    }),
    'grid'
  );
});

test('render mode resolves the branches in priority order', () => {
  assert.equal(
    getDeviceGridRenderMode({
      isInitialError: true,
      isInitialLoading: true,
      deviceCount: 3,
      filteredCount: 3
    }),
    'error'
  );
  assert.equal(
    getDeviceGridRenderMode({
      isInitialError: false,
      isInitialLoading: false,
      deviceCount: 0,
      filteredCount: 0
    }),
    'empty-fleet'
  );
  assert.equal(
    getDeviceGridRenderMode({
      isInitialError: false,
      isInitialLoading: false,
      deviceCount: 4,
      filteredCount: 0
    }),
    'empty-filter'
  );
});

test('an offline-only fleet still renders the grid, not an empty state', () => {
  // Offline devices are kept on the grid now; they must reach the grid branch
  // so the tile can paint its "offline" badge instead of vanishing mid-run.
  assert.equal(
    getDeviceGridRenderMode({
      isInitialError: false,
      isInitialLoading: false,
      deviceCount: 1,
      filteredCount: 1
    }),
    'grid'
  );
});

test('maps virtual rows to bounded device slices', () => {
  assert.equal(getDeviceGridRowCount(10, 4), 3);
  assert.deepEqual(getDeviceGridRowBounds(0, 4, 10), {
    start: 0,
    end: 4
  });
  assert.deepEqual(getDeviceGridRowBounds(2, 4, 10), {
    start: 8,
    end: 10
  });
});
