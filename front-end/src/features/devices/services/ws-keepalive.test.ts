import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEVICE_FARM_IDR_HARD_MIN_INTERVAL_MS,
  DEVICE_FARM_WS_FOCUS_STALE_MS,
  DEVICE_FARM_WS_RECONNECT_MAX_MS,
  isCurrentDeviceFarmWsEvent,
  nextReconnectDelayMs,
  shouldSendIdrRequest,
  shouldReconnectStaleSocketOnFocus
} from './ws-keepalive.ts';
import {
  H264_CACHED_KEY_STALE_MS,
  shouldInvalidateCachedH264KeyForConfig,
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

test('cached H264 keyframes are invalidated when config bytes change', () => {
  const first = new Uint8Array([0x10, 1, 65, 0, 10, 0, 20, 0, 1]).buffer;
  const same = new Uint8Array([0x10, 1, 65, 0, 10, 0, 20, 0, 1]).buffer;
  const changed = new Uint8Array([0x10, 1, 65, 0, 10, 0, 21, 0, 1]).buffer;

  assert.equal(shouldInvalidateCachedH264KeyForConfig(undefined, first), true);
  assert.equal(shouldInvalidateCachedH264KeyForConfig(first, same), false);
  assert.equal(shouldInvalidateCachedH264KeyForConfig(first, changed), true);
});

test('cached H264 keyframes survive a config_changed flag reset', () => {
  const changedFlag = new Uint8Array([
    0x10, 1, 65, 0, 10, 0, 20, 1, 1, 0x42, 0xe0, 0x1e
  ]).buffer;
  const stableFlag = new Uint8Array([
    0x10, 1, 65, 0, 10, 0, 20, 0, 1, 0x42, 0xe0, 0x1e
  ]).buffer;

  assert.equal(
    shouldInvalidateCachedH264KeyForConfig(changedFlag, stableFlag),
    false
  );
});

test('cached H264 keyframes are invalidated when config_changed is raised', () => {
  const stableFlag = new Uint8Array([
    0x10, 1, 65, 0, 10, 0, 20, 0, 1, 0x42, 0xe0, 0x1e
  ]).buffer;
  const changedFlag = new Uint8Array([
    0x10, 1, 65, 0, 10, 0, 20, 1, 1, 0x42, 0xe0, 0x1e
  ]).buffer;

  assert.equal(
    shouldInvalidateCachedH264KeyForConfig(stableFlag, changedFlag),
    true
  );
});

test('reconnect delay backs off and caps after repeated failed closes', () => {
  assert.equal(nextReconnectDelayMs(0), 500);
  assert.equal(nextReconnectDelayMs(1), 1_000);
  assert.equal(nextReconnectDelayMs(2), 2_000);
  assert.equal(nextReconnectDelayMs(10), DEVICE_FARM_WS_RECONNECT_MAX_MS);
});

test('socket lifecycle ignores stale events after a replacement socket exists', () => {
  const currentSocket = { id: 'new' };
  const staleSocket = { id: 'old' };

  assert.equal(isCurrentDeviceFarmWsEvent(currentSocket, currentSocket), true);
  assert.equal(isCurrentDeviceFarmWsEvent(currentSocket, staleSocket), false);
});

test('IDR requests keep a hard global floor even when callers request zero delay', () => {
  const lastSentAt = 1_000;
  assert.equal(shouldSendIdrRequest(lastSentAt, 1_100, 0), false);
  assert.equal(
    shouldSendIdrRequest(
      lastSentAt,
      lastSentAt + DEVICE_FARM_IDR_HARD_MIN_INTERVAL_MS,
      0
    ),
    true
  );
  assert.equal(shouldSendIdrRequest(lastSentAt, 1_800, 1_000), false);
  assert.equal(shouldSendIdrRequest(lastSentAt, 2_000, 1_000), true);
});
