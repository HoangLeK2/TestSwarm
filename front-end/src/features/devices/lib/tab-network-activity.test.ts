import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldRunTabNetworkActivity } from './tab-network-activity.ts';

test('tab network activity runs only while the tab is visible', () => {
  assert.equal(shouldRunTabNetworkActivity('visible'), true);
  assert.equal(shouldRunTabNetworkActivity('hidden'), false);
});

test('tab network activity is allowed when visibility is unavailable', () => {
  assert.equal(shouldRunTabNetworkActivity(undefined), true);
});
