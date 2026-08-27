import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getVariableDisplayMetadata,
  humanizeVariableName
} from './variable-display-metadata';

test('describes known runtime and social variables with stable metadata keys', () => {
  assert.deepEqual(
    getVariableDisplayMetadata('PLATFORM_SESSION_READY').labelKey,
    'variableInfo.labels.platformSessionReady'
  );
  assert.equal(
    getVariableDisplayMetadata('ENABLE_CONNECTION_REQUEST').category,
    'gate'
  );
  assert.equal(
    getVariableDisplayMetadata('PEOPLE_PROFILE_SELECTED').category,
    'profileResult'
  );
  assert.equal(
    getVariableDisplayMetadata('AUTHOR_PROFILE_OPENED').descriptionKey,
    'variableInfo.descriptions.authorProfileOpened'
  );
  assert.equal(
    getVariableDisplayMetadata('PLATFORM_SESSION_READY').originKey,
    'variableInfo.origins.platformSessionReady'
  );
  assert.equal(
    getVariableDisplayMetadata('ENABLE_CONNECTION_REQUEST').originKey,
    'variableInfo.origins.enableConnectionRequest'
  );
  assert.equal(
    getVariableDisplayMetadata('COMMENTER_PROFILE_OPENED').originKey,
    'variableInfo.origins.commenterProfileOpened'
  );
  assert.equal(
    getVariableDisplayMetadata('COMMENT_SHEET_OPENED').labelKey,
    'variableInfo.labels.commentSheetOpened'
  );
});

test('describes runtime outputs written by previous steps', () => {
  assert.equal(getVariableDisplayMetadata('_post_scan').category, 'stepOutput');
  assert.equal(
    getVariableDisplayMetadata('_people_target').originKey,
    'variableInfo.origins.peopleTarget'
  );
  assert.equal(
    getVariableDisplayMetadata('_custom_save_as').descriptionKey,
    'variableInfo.descriptions.genericStepOutput'
  );
});

test('describes assigned targets, source-pool groups, and loop-current values', () => {
  assert.equal(
    getVariableDisplayMetadata('TARGET_SELECTOR_VALUE').originKey,
    'variableInfo.origins.targetAssignment'
  );
  assert.equal(
    getVariableDisplayMetadata('GROUP_SEARCHES').originKey,
    'variableInfo.origins.groupTargets'
  );
  assert.equal(
    getVariableDisplayMetadata('GROUP_SEARCH_CURRENT').originKey,
    'variableInfo.origins.loopFromList'
  );
  assert.equal(
    getVariableDisplayMetadata('PAGE_ROW_TEXT_CURRENT').originKey,
    'variableInfo.origins.loopFromList'
  );
  assert.equal(
    getVariableDisplayMetadata('CANDIDATE_LEASE_TOKEN').originKey,
    'variableInfo.origins.candidateLease'
  );
  assert.equal(
    getVariableDisplayMetadata('CANDIDATE_SCORE').category,
    'targetData'
  );
});

test('describes built-in and account variables', () => {
  assert.equal(getVariableDisplayMetadata('__NOW__').category, 'builtIn');
  assert.equal(
    getVariableDisplayMetadata('__ACCOUNT_PASSWORD__').originKey,
    'variableInfo.origins.accountSecret'
  );
  assert.equal(
    getVariableDisplayMetadata('__ACCOUNT_LOGIN_STATE__').descriptionKey,
    'variableInfo.descriptions.genericAccount'
  );
});

test('classifies unknown variables by naming convention', () => {
  assert.equal(getVariableDisplayMetadata('GROUP_URL').category, 'targetData');
  assert.equal(
    getVariableDisplayMetadata('GROUP_URL').originKey,
    'variableInfo.origins.groupTargets'
  );
  assert.equal(
    getVariableDisplayMetadata('PAGE_CONTEXT').descriptionKey,
    'variableInfo.descriptions.genericPageData'
  );
  assert.equal(
    getVariableDisplayMetadata('PROFILE_2_ROW_TEXT').descriptionKey,
    'variableInfo.descriptions.genericProfileTarget'
  );
  assert.equal(
    getVariableDisplayMetadata('MAX_SCROLL_SECONDS').category,
    'crawlConfig'
  );
  assert.equal(
    getVariableDisplayMetadata('WELCOME_MESSAGE').category,
    'content'
  );
});

test('humanizes custom variable keys without changing the stored key', () => {
  assert.equal(humanizeVariableName('POST_RUN_SECONDS'), 'Post Run Seconds');
  assert.equal(
    getVariableDisplayMetadata('MY_CUSTOM_FLAG').fallbackLabel,
    'My Custom Flag'
  );
  assert.equal(
    getVariableDisplayMetadata('MY_CUSTOM_FLAG').descriptionKey,
    'variableInfo.descriptions.genericCustom'
  );
});
