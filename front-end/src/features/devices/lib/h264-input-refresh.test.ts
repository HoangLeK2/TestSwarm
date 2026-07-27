import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldRequestH264RefreshAfterInput } from './h264-input-refresh';

const baseOptions = {
  isActive: true,
  h264DecodeAllowed: true,
  h264Only: true,
  hasFrame: true,
  now: 10_000,
  lastRequestAt: 0
};

test('requests an IDR after input on a visible H264-only control stream', () => {
  assert.equal(shouldRequestH264RefreshAfterInput(baseOptions), true);
});

test('preserves the existing visible-frame policy for non-H264-only streams', () => {
  assert.equal(
    shouldRequestH264RefreshAfterInput({
      ...baseOptions,
      h264Only: false
    }),
    false
  );
});

test('requests an IDR while waiting for the first frame on any H264 stream', () => {
  assert.equal(
    shouldRequestH264RefreshAfterInput({
      ...baseOptions,
      h264Only: false,
      hasFrame: false
    }),
    true
  );
});

test('throttles repeated input IDR requests', () => {
  assert.equal(
    shouldRequestH264RefreshAfterInput({
      ...baseOptions,
      lastRequestAt: 8_000
    }),
    false
  );
});

test('skips an input IDR when a newer frame rendered during the wait window', () => {
  assert.equal(
    shouldRequestH264RefreshAfterInput({
      ...baseOptions,
      frameAdvancedSinceInput: true
    }),
    false
  );
});
