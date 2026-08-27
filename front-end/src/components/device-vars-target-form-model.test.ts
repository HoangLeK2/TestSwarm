import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEVICE_TARGET_FORM_KEY,
  applyDeviceTargetFormState,
  isDeviceTargetFormControlledKey,
  removeDeviceTargetFormState,
  readDeviceTargetFormState
} from './device-vars-target-form-model.ts';

test('target form materializes first facebook group into runtime-compatible variables', () => {
  const result = applyDeviceTargetFormState(
    { custom_note: 'keep-me', GROUP_NAME: 'stale' },
    {
      platform: 'facebook',
      selected: {
        group: [
          {
            id: 'group-1',
            display_name: 'OpenClaw VN',
            entity_type: 'group',
            platform: 'facebook',
            external_id: '123',
            canonical_url: 'https://facebook.com/groups/openclaw'
          }
        ],
        page: [],
        profile: []
      }
    }
  );

  assert.equal(result.custom_note, 'keep-me');
  assert.equal(result.TARGET_ENTITY_ID, 'group-1');
  assert.equal(result.TARGET_ENTITY_TYPE, 'group');
  assert.equal(result.TARGET_NAME, 'OpenClaw VN');
  assert.equal(result.GROUP_NAME, 'OpenClaw VN');
  assert.equal(result.TARGET_GROUP_NAME, 'OpenClaw VN');
  assert.equal(result.GROUP_COUNT, 1);
  assert.deepEqual(result.GROUP_SEARCHES, ['OpenClaw VN']);
  assert.deepEqual(result.GROUP_ROW_TEXTS, ['OpenClaw VN']);
  assert.deepEqual(result.GROUP_TARGET_IDS, ['group-1']);
  assert.deepEqual(result.GROUP_TARGETS, ['OpenClaw VN']);
  assert.equal(result.TARGET_SELECTOR_BY, 'descriptionStartsWith');
  assert.equal(result.TARGET_SELECTOR_VALUE, 'OpenClaw VN,');
});

test('target form keeps all selected targets grouped by platform type', () => {
  const result = applyDeviceTargetFormState(
    {},
    {
      platform: 'facebook',
      selected: {
        group: [
          {
            id: 'group-1',
            display_name: 'Group One',
            entity_type: 'group',
            platform: 'facebook'
          }
        ],
        page: [
          {
            id: 'page-1',
            display_name: 'Page One',
            entity_type: 'page',
            platform: 'facebook'
          }
        ],
        profile: [
          {
            id: 'profile-1',
            display_name: 'Profile One',
            entity_type: 'profile',
            platform: 'facebook'
          }
        ]
      }
    }
  );

  assert.deepEqual(result.TARGET_ENTITY_IDS, [
    'group-1',
    'page-1',
    'profile-1'
  ]);
  assert.deepEqual(result.PAGE_TARGETS, ['Page One']);
  assert.deepEqual(result.PROFILE_TARGET_IDS, ['profile-1']);
  assert.equal(result.GROUP_COUNT, 1);
  assert.deepEqual(result.GROUP_SEARCHES, ['Group One']);
  assert.deepEqual(result.GROUP_ROW_TEXTS, ['Group One']);
});

test('target form read normalizes invalid metadata without losing valid selections', () => {
  const state = readDeviceTargetFormState({
    [DEVICE_TARGET_FORM_KEY]: {
      platform: 'facebook',
      selected: {
        group: [
          { id: 'group-1', display_name: 'Group One', entity_type: 'group' },
          { id: 'group-1', display_name: 'Group One', entity_type: 'group' },
          { id: '', display_name: 'Missing id', entity_type: 'group' }
        ],
        page: 'bad'
      }
    }
  });

  assert.equal(state.platform, 'facebook');
  assert.deepEqual(
    state.selected.group.map((target) => target.id),
    ['group-1']
  );
  assert.deepEqual(state.selected.page, []);
});

test('target form exposes controlled keys so generic form can hide generated runtime fields', () => {
  assert.equal(isDeviceTargetFormControlledKey(DEVICE_TARGET_FORM_KEY), true);
  assert.equal(isDeviceTargetFormControlledKey('TARGET_ENTITY_ID'), true);
  assert.equal(isDeviceTargetFormControlledKey('GROUP_TARGETS'), true);
  assert.equal(isDeviceTargetFormControlledKey('GROUP_SEARCHES'), true);
  assert.equal(isDeviceTargetFormControlledKey('GROUP_ROW_TEXTS'), true);
  assert.equal(isDeviceTargetFormControlledKey('GROUP_COUNT'), true);
  assert.equal(isDeviceTargetFormControlledKey('PAGE_TARGETS'), true);
  assert.equal(isDeviceTargetFormControlledKey('custom_note'), false);
  assert.equal(isDeviceTargetFormControlledKey('PAGE_KEYWORDS'), false);
});

test('target form removal keeps custom variables and strips generated target fields', () => {
  const result = removeDeviceTargetFormState({
    custom_note: 'keep',
    PAGE_KEYWORDS: ['hotel'],
    [DEVICE_TARGET_FORM_KEY]: { platform: 'facebook', selected: {} },
    TARGET_ENTITY_ID: 'target-1',
    GROUP_TARGETS: ['Group One'],
    GROUP_SEARCHES: ['Group One'],
    GROUP_ROW_TEXTS: ['Group One'],
    GROUP_COUNT: 1
  });

  assert.deepEqual(result, {
    custom_note: 'keep',
    PAGE_KEYWORDS: ['hotel']
  });
});
