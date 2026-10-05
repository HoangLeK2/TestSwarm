import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ALL_STEP_TYPES,
  createDefaultFbCommentThenSteps,
  createDefaultStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './types.ts';

test('step dropdown hides legacy compound fb comment node', () => {
  const exposedTypes = new Set(
    ALL_STEP_TYPES.map((stepType) => stepType.value)
  );

  assert.equal(exposedTypes.has('social_find_comment_button'), true);
  assert.equal(exposedTypes.has('social_tap_comment_target'), true);
  assert.equal(exposedTypes.has('social_apply_comment_filter'), true);
  assert.equal(exposedTypes.has('social_open_comments'), false);
  assert.equal(exposedTypes.has('social_open_comments'), false);
});

test('step dropdown values are unique', () => {
  const values = ALL_STEP_TYPES.map((stepType) => stepType.value);
  const duplicates = values.filter(
    (value, index) => values.indexOf(value) !== index
  );

  assert.deepEqual(duplicates, []);
  assert.equal(values.includes('install_apk'), true);
  assert.equal(values.includes('extract_text_ocr'), true);
});

test('social action dropdown labels are platform-neutral', () => {
  const labelsByType = new Map(
    ALL_STEP_TYPES.map((stepType) => [stepType.value, stepType.label])
  );

  assert.equal(labelsByType.get('connection_request'), 'Gửi yêu cầu kết nối');
  assert.equal(labelsByType.get('community_membership'), 'Tham gia cộng đồng');
  assert.equal(
    labelsByType.get('social_scan_posts_interact'),
    'Quét và tương tác nội dung'
  );
  assert.equal(
    labelsByType.get('platform_session_gate'),
    'Kiểm tra phiên nền tảng'
  );
  assert.equal(
    [...labelsByType.values()].some((label) => label.includes('(FB)')),
    false
  );
});

test('generic extract default does not force Instagram', () => {
  const step = createDefaultStep('extract');

  assert.equal(step.type, 'extract');
  assert.equal(step.entity, 'posts');
  assert.equal(step.platform, 'auto');
  assert.equal(step.content_type, 'post');
  assert.equal(step.dedupe_field, 'post_key');
});

test('default fb comment extract uses balanced fast crawl budget', () => {
  const step = createDefaultStep('extract_comments');

  assert.equal(step.max_items, 220);
  assert.equal(step.comment_scroll_passes, 16);
  assert.equal(step.comment_swipes_per_dump, 4);
  assert.equal(step.comment_max_snapshots, 12);
  assert.equal(step.comment_scroll_wall_s, 25);
  assert.equal(step.comment_no_growth_break, 0);
  assert.equal(step.comment_stop_if_no_new, false);
  assert.equal(step.stop_if_no_new, false);
  assert.equal(step.open_post_press_back_after_extract, true);
});

test('default fb comment sequence keeps back inside extract step', () => {
  const steps = createDefaultFbCommentThenSteps();
  const extract = steps.find(
    (step) => step.type === 'extract' && step.entity === 'comments'
  );

  assert.ok(extract);
  assert.equal(extract.open_post_press_back_after_extract, true);
  assert.equal(
    steps.some((step) => step.type === 'key' && step.key === 'back'),
    false
  );
});

test('custom fb comment crawl budget survives frontend JSON payload', () => {
  const step = {
    ...createDefaultStep('extract_comments'),
    max_items: 333,
    comment_scroll_passes: 27,
    comment_swipes_per_dump: 5,
    comment_max_snapshots: 18,
    comment_scroll_wall_s: 44,
    comment_stop_if_no_new: false,
    stop_if_no_new: false,
    no_new_threshold: 6
  };

  const payload = JSON.parse(JSON.stringify(step));

  assert.equal(payload.max_items, 333);
  assert.equal(payload.comment_scroll_passes, 27);
  assert.equal(payload.comment_swipes_per_dump, 5);
  assert.equal(payload.comment_max_snapshots, 18);
  assert.equal(payload.comment_scroll_wall_s, 44);
  assert.equal(payload.comment_stop_if_no_new, false);
  assert.equal(payload.stop_if_no_new, false);
  assert.equal(payload.no_new_threshold, 6);
});

test('app automation default steps include editable profile shells', () => {
  const login = createDefaultStep('login_if_needed');
  const sessionGate = createDefaultStep('platform_session_gate');
  const form = createDefaultStep('fill_form');
  const assertState = createDefaultStep('assert_app_state');

  assert.equal(login.type, 'login_if_needed');
  assert.equal(login.profile.package, '');
  assert.deepEqual(login.profile.login_recipe.detect_logged_in.any_text, []);
  assert.equal(sessionGate.type, 'platform_session_gate');
  assert.equal(sessionGate.phase, 'preflight');
  assert.equal(sessionGate.timeout, 0);

  assert.equal(form.type, 'fill_form');
  assert.deepEqual(form.profile.form_recipes, {});

  assert.equal(assertState.type, 'assert_app_state');
  assert.deepEqual(assertState.any_text, []);
});

test('verify screen defaults to stored image template setup', () => {
  const step = createDefaultStep('verify_screen');

  assert.equal(step.type, 'verify_screen');
  assert.equal(step.template_key, '');
  assert.equal(step.ssim_threshold, 0.75);
  assert.equal(step.timeout, 8);
  assert.equal(step.poll, 0.5);
  assert.equal('screenshot' in step, false);
});
