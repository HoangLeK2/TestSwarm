import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildSourcePoolInput,
  isAllocatableSourceStatus,
  listSourcePoolOptions
} from './dispatch-source-pool.ts';

test('source pool options group catalog rows by generic platform and type', () => {
  const options = listSourcePoolOptions([
    { platform: 'facebook', entity_type: 'group' },
    { platform: 'facebook', entity_type: 'group' },
    { platform: 'facebook', entity_type: 'profile' },
    { platform: 'zalo', entity_type: 'group' }
  ]);

  assert.deepEqual(options, [
    {
      key: 'facebook::group',
      platform: 'facebook',
      entityType: 'group',
      count: 2
    },
    {
      key: 'facebook::profile',
      platform: 'facebook',
      entityType: 'profile',
      count: 1
    },
    {
      key: 'zalo::group',
      platform: 'zalo',
      entityType: 'group',
      count: 1
    }
  ]);
});

test('allocatable statuses match the backend source-pool default', () => {
  assert.equal(isAllocatableSourceStatus('candidate'), true);
  assert.equal(isAllocatableSourceStatus(' ACTIVE '), true);
  assert.equal(isAllocatableSourceStatus('available'), true);
  assert.equal(isAllocatableSourceStatus('resolved'), false);
  assert.equal(isAllocatableSourceStatus('archived'), false);
});

test('source pool input trims search and keeps the contract platform-neutral', () => {
  assert.deepEqual(buildSourcePoolInput('facebook::group', ' OpenClaw '), {
    platform: 'facebook',
    entity_type: 'group',
    search: 'OpenClaw'
  });
  assert.deepEqual(buildSourcePoolInput('zalo::profile', '   '), {
    platform: 'zalo',
    entity_type: 'profile'
  });
});
