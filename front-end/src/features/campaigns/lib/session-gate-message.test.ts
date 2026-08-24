import assert from 'node:assert/strict';
import test from 'node:test';

import { humanizeSessionGateMessage } from './session-gate-message.ts';

const t = (key: string, values?: Record<string, string | number>) =>
  values
    ? `${key}(${Object.entries(values)
        .map(([k, v]) => `${k}=${v}`)
        .join(',')})`
    : key;

test('maps the checkpoint block an operator cannot read', () => {
  assert.equal(
    humanizeSessionGateMessage(
      'platform_session_gate preflight blocked: checkpoint_visible',
      t
    ),
    'sessionGateCheckpoint'
  );
});

test('maps every readiness and verdict reason the gate can block on', () => {
  const cases: [string, string][] = [
    ['login_surface_visible', 'sessionGateLoggedOut'],
    ['app_unresponsive', 'sessionGateAppUnresponsive'],
    ['facebook_package_not_visible', 'sessionGateAppNotVisible'],
    ['hierarchy_unavailable', 'sessionGateScreenUnreadable'],
    ['invalid_hierarchy', 'sessionGateScreenUnreadable'],
    ['readiness_markers_not_found', 'sessionGateScreenUnknown'],
    ['platform_readiness_not_implemented', 'sessionGateUnsupportedPlatform'],
    ['facebook_session_account_mismatch', 'sessionGateAccountMismatch'],
    [
      'facebook_ready_without_matching_provenance',
      'sessionGateUntrustedSession'
    ],
    ['facebook_login_provenance_missing', 'sessionGateLoginNotConfirmed']
  ];
  for (const [reason, key] of cases) {
    assert.equal(
      humanizeSessionGateMessage(
        `platform_session_gate confirm blocked: ${reason}`,
        t
      ),
      key
    );
  }
});

test('keeps an unmapped reason visible instead of dropping it', () => {
  assert.equal(
    humanizeSessionGateMessage(
      'platform_session_gate preflight blocked: some_new_reason',
      t
    ),
    'sessionGateBlockedOther(reason=some_new_reason)'
  );
});

test('maps gate resolution failures to their cause', () => {
  assert.equal(
    humanizeSessionGateMessage(
      'platform_session_gate failed: Facebook session gate requires an execution account',
      t
    ),
    'sessionGateNoRunAccount'
  );
  assert.equal(
    humanizeSessionGateMessage(
      'platform_session_gate failed: Facebook session gate device is not part of the execution',
      t
    ),
    'sessionGateDeviceNotInRun'
  );
});

test('carries an unknown failure detail through', () => {
  assert.equal(
    humanizeSessionGateMessage('platform_session_gate failed: boom', t),
    'sessionGateFailed(detail=boom)'
  );
});

test('maps the unsupported platform message', () => {
  assert.equal(
    humanizeSessionGateMessage(
      "platform_session_gate: platform 'tiktok' does not implement this step",
      t
    ),
    'sessionGateUnsupportedPlatform'
  );
});

test('maps the non-blocking outcomes', () => {
  assert.equal(
    humanizeSessionGateMessage(
      'platform_session_gate preflight: ready (facebook_session_ready)',
      t
    ),
    'sessionGateReady'
  );
  assert.equal(
    humanizeSessionGateMessage(
      'platform_session_gate preflight: login required (facebook_login_required)',
      t
    ),
    'sessionGateLoginRequired'
  );
});

test('leaves other step messages to their own renderer', () => {
  assert.equal(humanizeSessionGateMessage('tap: selector not found', t), null);
  assert.equal(humanizeSessionGateMessage('', t), null);
  assert.equal(humanizeSessionGateMessage(null, t), null);
});
