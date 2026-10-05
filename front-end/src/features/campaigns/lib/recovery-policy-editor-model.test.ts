import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createDefaultRecoveryRule,
  normalizeRecoveryPolicyForEditor,
  normalizeRecoveryRuleForEditor
} from './recovery-policy-editor-model.ts';

test('normalizeRecoveryRuleForEditor always makes recovery campaign-wide', () => {
  const rule = normalizeRecoveryRuleForEditor({
    incident_type: 'app_popup',
    scope: {
      step_type_any: ['ig_comment'],
      step_id_any: ['comment-step'],
      strategy_any: ['comments'],
      step_index_any: [3]
    },
    scenario_id: 'recover-popup',
    outcome: 'retry_step',
    max_attempts: 2
  });

  assert.deepEqual(rule.scope, {});
  assert.equal(rule.scenario_id, 'recover-popup');
  assert.equal(rule.on_success, 'retry_step');
  assert.equal(rule.max_attempts, 2);
});

test('normalizeRecoveryRuleForEditor strips hidden step-scoped match filters', () => {
  const rule = normalizeRecoveryRuleForEditor({
    incident_type: 'unknown',
    scenario_id: 'recover-any',
    match: {
      step_type_any: ['ig_comment'],
      strategy_any: ['comments'],
      text_any: ['try again'],
      package_any: ['com.instagram.android']
    }
  });

  assert.deepEqual(rule.scope, {});
  assert.deepEqual(rule.match, {
    text_any: ['try again'],
    package_any: ['com.instagram.android']
  });
});

test('normalizeRecoveryRuleForEditor removes empty match after stripping step filters', () => {
  const rule = normalizeRecoveryRuleForEditor({
    scenario_id: 'recover-any',
    match: {
      step_type_any: ['ig_comment'],
      strategy_any: ['comments']
    }
  });

  assert.equal(rule.match, undefined);
});

test('normalizeRecoveryRuleForEditor clamps attempts and timeout boundaries', () => {
  const tooLow = normalizeRecoveryRuleForEditor({
    scenario_id: 'recover-any',
    max_attempts: 0,
    timeout_ms: 100
  });
  const tooHigh = normalizeRecoveryRuleForEditor({
    scenario_id: 'recover-any',
    max_attempts: 99,
    timeout_ms: 999_999
  });

  assert.equal(tooLow.max_attempts, 1);
  assert.equal(tooLow.timeout_ms, 5_000);
  assert.equal(tooHigh.max_attempts, 10);
  assert.equal(tooHigh.timeout_ms, 180_000);
});

test('normalizeRecoveryPolicyForEditor preserves incident and run budgets', () => {
  const policy = normalizeRecoveryPolicyForEditor({
    enabled: true,
    max_total_attempts: 999_999,
    max_attempts_per_step: 999,
    rules: []
  });

  assert.equal(policy.max_total_attempts, 10_000);
  assert.equal(policy.max_attempts_per_step, 20);

  const defaults = normalizeRecoveryPolicyForEditor({ enabled: true });
  assert.equal(defaults.max_total_attempts, 100);
  assert.equal(defaults.max_attempts_per_step, 2);
});

test('normalizeRecoveryPolicyForEditor normalizes every rule and keeps disabled empty', () => {
  assert.deepEqual(normalizeRecoveryPolicyForEditor(null), {
    enabled: false,
    max_total_attempts: 100,
    max_attempts_per_step: 2,
    rules: []
  });

  const policy = normalizeRecoveryPolicyForEditor({
    enabled: true,
    max_total_attempts: 100,
    max_attempts_per_step: 2,
    rules: [
      {
        incident_type: 'profile_page',
        scope: { step_id_any: ['old-step'] },
        scenario_id: 'recover-profile',
        outcome: 'continue'
      },
      {
        incident_types: ['login_or_checkpoint'],
        scope: { strategy_any: ['comments'] },
        scenario_id: 'recover-login',
        outcome: 'pause_for_takeover'
      }
    ]
  });

  assert.equal(policy.enabled, true);
  assert.equal(policy.rules?.length, 2);
  assert.deepEqual(policy.rules?.[0]?.scope, {});
  assert.equal(policy.rules?.[0]?.on_success, 'continue');
  assert.deepEqual(policy.rules?.[1]?.scope, {});
  assert.equal(policy.rules?.[1]?.on_success, 'retry_step');
});

test('createDefaultRecoveryRule creates a campaign-wide retry rule', () => {
  assert.deepEqual(createDefaultRecoveryRule('recover-default'), {
    incident_type: 'unknown',
    incident_types: ['unknown'],
    scope: {},
    match: undefined,
    scenario_id: 'recover-default',
    scenario_name: null,
    outcome: 'retry_step',
    on_success: 'retry_step',
    on_failure: 'fail',
    max_attempts: 1,
    timeout_ms: 60_000
  });
});
