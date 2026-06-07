import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEVICE_FARM_WS_FOCUS_STALE_MS,
  nextReconnectDelayMs,
  shouldReconnectStaleSocketOnFocus
} from './ws-keepalive.ts';
import {
  H264_CACHED_KEY_STALE_MS,
  shouldReplayCachedKeyFrameAge
} from './h264-cache.ts';

test('focus stale check ignores sockets that have not received a server frame yet', () => {
  assert.equal(
    shouldReconnectStaleSocketOnFocus(0, DEVICE_FARM_WS_FOCUS_STALE_MS * 2),
    false
  );
});

test('focus stale check reconnects after the configured quiet window', () => {
  assert.equal(
    shouldReconnectStaleSocketOnFocus(
      1_000,
      1_000 + DEVICE_FARM_WS_FOCUS_STALE_MS + 1
    ),
    true
  );
});

test('cached H264 keyframes are replayed only while very fresh', () => {
  assert.equal(shouldReplayCachedKeyFrameAge(0), true);
  assert.equal(shouldReplayCachedKeyFrameAge(H264_CACHED_KEY_STALE_MS), true);
  assert.equal(
    shouldReplayCachedKeyFrameAge(H264_CACHED_KEY_STALE_MS + 1),
    false
  );
  assert.equal(shouldReplayCachedKeyFrameAge(Infinity), false);
});

test('reconnect delay backs off and caps after repeated failed closes', () => {
  assert.equal(nextReconnectDelayMs(0), 2_000);
  assert.equal(nextReconnectDelayMs(1), 4_000);
  assert.equal(nextReconnectDelayMs(2), 8_000);
  assert.equal(nextReconnectDelayMs(10), 30_000);
});
