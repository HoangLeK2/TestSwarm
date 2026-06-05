import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_STEP_RETRY_POLICY,
  coerceStepRetryPolicy,
  formatRetryReasons,
  parseRetryReasons,
  retryPatchForEnabledState,
  withRetryField
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-retry-policy.ts';

test('retryPatchForEnabledState enables retry with backend-safe defaults', () => {
  assert.deepEqual(retryPatchForEnabledState({ type: 'wait' }, true), {
    retry: DEFAULT_STEP_RETRY_POLICY
  });
});

test('retryPatchForEnabledState disables retry by removing the field', () => {
  assert.deepEqual(
    retryPatchForEnabledState(
      { type: 'wait', retry: { max_attempts: 3 } },
      false
    ),
    { retry: undefined }
  );
});

test('coerceStepRetryPolicy clamps numeric fields to backend limits', () => {
  const policy = coerceStepRetryPolicy({
    max_attempts: 99,
    backoff_ms: -1,
    backoff_cap_ms: 99_999,
    backoff_strategy: 'fixed',
    jitter: 2
  });

  assert.equal(policy.max_attempts, 10);
  assert.equal(policy.backoff_ms, 0);
  assert.equal(policy.backoff_cap_ms, 60_000);
  assert.equal(policy.backoff_strategy, 'fixed');
  assert.equal(policy.jitter, 1);
});

test('parseRetryReasons accepts comma and newline separated reason codes', () => {
  assert.deepEqual(
    parseRetryReasons('timeout, stale_frame\n element_not_ready ,, timeout'),
    ['timeout', 'stale_frame', 'element_not_ready']
  );
});

test('formatRetryReasons handles retryable_reasons and legacy on field', () => {
  assert.equal(
    formatRetryReasons({ retryable_reasons: ['timeout', 'network'] }),
    'timeout, network'
  );
  assert.equal(formatRetryReasons({ on: ['stale_frame'] }), 'stale_frame');
});

test('withRetryField omits empty retryable reasons', () => {
  assert.deepEqual(withRetryField({}, 'retryable_reasons', []), {
    max_attempts: 3,
    backoff_ms: 1000,
    backoff_strategy: 'exponential',
    jitter: 0.2
  });
});
