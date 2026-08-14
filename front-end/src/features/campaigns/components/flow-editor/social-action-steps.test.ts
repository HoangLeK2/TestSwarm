import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

import {
  getInsertMenuForUi
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './constants.ts';
import {
  getSocialActionOptions
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './social-action-options.ts';
import {
  createDefaultStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../scenario-steps/types.ts';

const require = createRequire(import.meta.url);
const enMessages = require('../../../../../messages/en.json');
const viMessages = require('../../../../../messages/vi.json');

const translate = (key: string) => key;

function flowInsertTranslator(messages: unknown) {
  const root = (
    messages as {
      campaignsFeature?: { flowInsert?: Record<string, unknown> };
    }
  ).campaignsFeature?.flowInsert;

  return (key: string): string => {
    const value = key
      .split('.')
      .reduce<unknown>(
        (current, part) =>
          current && typeof current === 'object'
            ? (current as Record<string, unknown>)[part]
            : undefined,
        root
      );

    if (typeof value !== 'string') {
      throw new Error(`MISSING_MESSAGE ${key}`);
    }

    return value;
  };
}

for (const [locale, messages] of [
  ['en', enMessages],
  ['vi', viMessages]
] as const) {
  test(`renders the full insert menu with ${locale} flowInsert messages`, () => {
    assert.doesNotThrow(() =>
      getInsertMenuForUi(flowInsertTranslator(messages))
    );
  });
}

for (const [type, action] of [
  ['content_interaction', 'like'],
  ['connection_request', 'request'],
  ['community_membership', 'join']
] as const) {
  test(`creates a safe default for ${type}`, () => {
    const step = createDefaultStep(type);

    assert.equal(step.type, type);
    assert.equal(step.platform, 'facebook');
    assert.equal(step.action, action);
    assert.equal(step.timeout, 6);
    assert.equal(step.poll, 0.4);
    assert.equal(step.verify_timeout, 5);
  });
}

test('exposes all actions in the Facebook insert group', () => {
  const facebook = getInsertMenuForUi(translate).find(
    (group) => group.groupKey === 'facebook'
  );
  const types = new Set(facebook?.items.map((item) => item.type) ?? []);

  assert.equal(types.has('content_interaction'), true);
  assert.equal(types.has('connection_request'), true);
  assert.equal(types.has('community_membership'), true);
  assert.equal(types.has('fb_select_people_profile'), true);
  assert.equal(types.has('fb_connect_visible_people'), true);
  assert.equal(types.has('fb_select_post_target'), true);
  assert.equal(types.has('fb_scan_posts_interact'), true);
  assert.equal(types.has('social_open_author_from_post_match'), true);
});

test('creates a default Facebook people profile resolver', () => {
  const step = createDefaultStep('fb_select_people_profile');

  assert.equal(step.type, 'fb_select_people_profile');
  assert.equal(step.save_as, '_people_target');
  assert.equal(step.min_score, 80);
  assert.equal(step.require_unique, true);
  assert.deepEqual(step.required_keywords, []);
});

test('creates a default Facebook visible common-context connector', () => {
  const step = createDefaultStep('fb_connect_visible_people');

  assert.equal(step.type, 'fb_connect_visible_people');
  assert.equal(step.platform, 'facebook');
  assert.equal(step.save_as, '_visible_connection_action');
  assert.equal(step.min_score, 40);
  assert.equal(step.require_common, true);
  assert.deepEqual(step.common_keywords, [
    'bạn chung',
    'mutual friends',
    'cùng nhóm'
  ]);
});

test('creates a default Facebook post target resolver', () => {
  const step = createDefaultStep('fb_select_post_target');

  assert.equal(step.type, 'fb_select_post_target');
  assert.equal(step.save_as, '_post_target');
  assert.equal(step.min_score, 80);
  assert.equal(step.require_unique, true);
  assert.deepEqual(step.required_keywords, []);
});

test('creates a default Facebook post feed scanner', () => {
  const step = createDefaultStep('fb_scan_posts_interact');

  assert.equal(step.type, 'fb_scan_posts_interact');
  assert.equal(step.platform, 'facebook');
  assert.equal(step.save_as, '_post_scan');
  assert.equal(step.target_count, 1);
  assert.equal(step.max_scrolls, 6);
  assert.equal(step.require_comment, true);
  assert.deepEqual(step.keywords, []);
});

test('creates a default social author-from-post resolver', () => {
  const step = createDefaultStep('social_open_author_from_post_match');

  assert.equal(step.type, 'social_open_author_from_post_match');
  assert.equal(step.platform, 'facebook');
  assert.equal(step.source_var, '_post_scan');
  assert.equal(step.action_index, 0);
  assert.equal(step.save_as, '_people_target');
  assert.equal(step.save_success_as, 'PEOPLE_PROFILE_SELECTED');
  assert.equal(step.save_opened_as, 'AUTHOR_PROFILE_OPENED');
  assert.deepEqual(step.required_keywords, []);
});

test('content interaction exposes like, comment, and share choices', () => {
  assert.deepEqual(getSocialActionOptions('content_interaction'), [
    { value: 'like', label: 'Thích bài viết' },
    { value: 'comment', label: 'Bình luận' },
    { value: 'share', label: 'Chia sẻ' }
  ]);
});
