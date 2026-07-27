import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isGridH264Enabled,
  nextSnapshotRetryDelayMs,
  selectDeviceTilePreviewMode
} from './device-tile-preview-policy';

test('enables H264 by default while preserving an explicit off switch', () => {
  assert.equal(isGridH264Enabled(undefined), true);
  assert.equal(isGridH264Enabled('1'), true);
  assert.equal(isGridH264Enabled('0'), false);
});

test('uses H264 without screenshot polling when WebCodecs is available', () => {
  assert.deepEqual(
    selectDeviceTilePreviewMode({
      h264Enabled: true,
      webCodecsSupport: 'supported',
      h264Stalled: false
    }),
    {
      useH264: true,
      useSnapshot: false
    }
  );
});

test('waits for capability detection and only falls back when necessary', () => {
  assert.deepEqual(
    selectDeviceTilePreviewMode({
      h264Enabled: true,
      webCodecsSupport: 'unknown',
      h264Stalled: false
    }),
    { useH264: false, useSnapshot: false }
  );
  assert.deepEqual(
    selectDeviceTilePreviewMode({
      h264Enabled: true,
      webCodecsSupport: 'unsupported',
      h264Stalled: false
    }),
    { useH264: false, useSnapshot: true }
  );
  assert.deepEqual(
    selectDeviceTilePreviewMode({
      h264Enabled: true,
      webCodecsSupport: 'supported',
      h264Stalled: true
    }),
    { useH264: true, useSnapshot: true }
  );
});

test('backs off failed screenshot fallback requests up to 15 seconds', () => {
  assert.deepEqual(
    [1, 2, 3, 4, 5].map((consecutiveFailureCount) =>
      nextSnapshotRetryDelayMs({
        consecutiveFailureCount,
        refreshMs: 2_000
      })
    ),
    [2_000, 4_000, 8_000, 15_000, 15_000]
  );
});
