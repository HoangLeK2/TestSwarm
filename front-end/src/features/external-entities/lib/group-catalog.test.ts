import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildGroupCatalogParams,
  getGroupMemberCount,
  getGroupOpenMode,
  getGroupPrivacy,
  getSafeGroupUrl,
  isGroupStale
} from './group-catalog.ts';

test('group availability distinguishes direct, searchable, and unusable records', () => {
  assert.equal(
    getGroupOpenMode({
      canonical_url: 'https://facebook.com/groups/123',
      current_attributes: {}
    }),
    'direct'
  );
  assert.equal(
    getGroupOpenMode({
      current_attributes: {
        locator: {
          search_query: 'OpenClaw Việt Nam',
          selector: { by: 'descriptionStartsWith', value: 'OpenClaw Việt Nam,' }
        }
      }
    }),
    'search'
  );
  assert.equal(
    getGroupOpenMode({
      current_attributes: {}
    }),
    'unavailable'
  );
});

test('group links only allow http and https URLs', () => {
  assert.equal(
    getSafeGroupUrl({ canonical_url: 'https://facebook.com/groups/123' }),
    'https://facebook.com/groups/123'
  );
  assert.equal(getSafeGroupUrl({ canonical_url: 'javascript:alert(1)' }), null);
  assert.equal(
    getSafeGroupUrl({ canonical_url: 'https://facebook.com.example/groups/1' }),
    null
  );
  assert.equal(
    getSafeGroupUrl({ canonical_url: 'https://m.facebook.com/groups/1' }),
    'https://m.facebook.com/groups/1'
  );
  assert.equal(
    getSafeGroupUrl({ canonical_url: 'https://facebook.com/openclaw' }),
    null
  );
});

test('group catalog queries are always scoped to Facebook groups', () => {
  assert.deepEqual(
    buildGroupCatalogParams({
      search: ' openclaw ',
      status: 'candidate',
      limit: 25,
      offset: 50
    }),
    {
      platform: 'facebook',
      entity_type: 'group',
      search: 'openclaw',
      status: 'candidate',
      limit: 25,
      offset: 50
    }
  );
});

test('group presentation reads the normalized crawl snapshot', () => {
  const entity = {
    current_attributes: { privacy: 'public' },
    current_metrics: { member_count: 315_000 },
    last_seen_at: '2026-07-20T00:00:00Z'
  };

  assert.equal(getGroupPrivacy(entity), 'public');
  assert.equal(getGroupMemberCount(entity), 315_000);
  assert.equal(isGroupStale(entity, new Date('2026-07-27T00:00:01Z'), 7), true);
});
