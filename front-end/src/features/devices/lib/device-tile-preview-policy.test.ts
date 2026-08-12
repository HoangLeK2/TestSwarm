import assert from 'node:assert/strict';
import test from 'node:test';

import {
  hasMediaPlanePreview,
  isGridH264Enabled,
  isGridWebRtcPreviewEnabled,
  isDevicePreviewStreamEligible,
  nextSnapshotRetryDelayMs,
  selectDeviceTilePreviewMode
} from './device-tile-preview-policy';

test('enables H264 by default while preserving an explicit off switch', () => {
  assert.equal(isGridH264Enabled(undefined), true);
  assert.equal(isGridH264Enabled('1'), true);
  assert.equal(isGridH264Enabled('0'), false);
});

test('keeps dashboard WebRTC previews on by default with an explicit off switch', () => {
  assert.equal(isGridWebRtcPreviewEnabled(undefined), true);
  assert.equal(isGridWebRtcPreviewEnabled('0'), false);
  assert.equal(isGridWebRtcPreviewEnabled('1'), true);
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

test('keeps dashboard preview eligible from media-plane even when control-plane is offline', () => {
  assert.equal(
    isDevicePreviewStreamEligible(
      { state: 'DISCONNECTED', media_adapter_connected: true },
      false
    ),
    true
  );
  assert.equal(
    isDevicePreviewStreamEligible(
      { state: 'DEAD', media_stream_connected: true },
      false
    ),
    true
  );
  assert.equal(
    isDevicePreviewStreamEligible({ state: 'DISCONNECTED' }, false),
    false
  );
});

test('detects media-plane preview independently from agent/control state', () => {
  assert.equal(hasMediaPlanePreview({ media_adapter_connected: true }), true);
  assert.equal(hasMediaPlanePreview({ media_stream_active: true }), true);
  assert.equal(hasMediaPlanePreview({ media_stream_connected: true }), true);
  assert.equal(hasMediaPlanePreview({}), false);
});
