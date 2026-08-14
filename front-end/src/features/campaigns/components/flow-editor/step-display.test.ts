import assert from 'node:assert/strict';
import test from 'node:test';
import {
  getStepDisplay,
  getStepTypeName,
  getVariableDisplayName
} from './constants.ts';

const labels: Record<string, string> = {
  'typeName.facebook_session_gate': 'KIỂM TRA PHIÊN NỀN TẢNG',
  'display.platformSessionPreflight': 'Kiểm tra trước khi tiếp tục',
  'systemVariable.platformSessionReady': 'Phiên nền tảng sẵn sàng'
};

const t = (key: string) => labels[key] ?? `campaignsFeature.flowStep.${key}`;

test('localizes the platform session node without exposing Facebook internals', () => {
  assert.equal(
    getStepTypeName('facebook_session_gate', t),
    'KIỂM TRA PHIÊN NỀN TẢNG'
  );
  assert.deepEqual(
    getStepDisplay({ type: 'facebook_session_gate', phase: 'preflight' }, t),
    { target: 'Kiểm tra trước khi tiếp tục' }
  );
  assert.equal(
    getVariableDisplayName('FACEBOOK_SESSION_READY', t),
    'Phiên nền tảng sẵn sàng'
  );
});

test('keeps user-authored variable names unchanged', () => {
  assert.equal(
    getVariableDisplayName('MY_CUSTOM_VARIABLE', t),
    'MY_CUSTOM_VARIABLE'
  );
});
