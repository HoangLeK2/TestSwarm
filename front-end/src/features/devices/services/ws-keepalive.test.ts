import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEVICE_FARM_WS_FOCUS_STALE_MS,
  shouldReconnectStaleSocketOnFocus
} from './ws-keepalive.ts';

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
