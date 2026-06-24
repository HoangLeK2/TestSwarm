import assert from 'node:assert/strict';
import test from 'node:test';
import { summarizeDispatchResult } from './campaign-dispatch-result.ts';

test('summarizeDispatchResult treats single busy-device claim failure as terminal', () => {
  const summary = summarizeDispatchResult({
    target_count: 1,
    executions: [
      {
        execution_id: 'exec-1',
        device_id: 'device-1',
        status: 'failed',
        failure_reason: 'device_claim_failed',
        workflow_id: null
      } as any
    ]
  });

  assert.equal(summary.total, 1);
  assert.equal(summary.failed, 1);
  assert.equal(summary.deviceClaimFailed, 1);
  assert.equal(summary.allTerminal, true);
  assert.equal(summary.allFailed, true);
  assert.equal(summary.allFailuresAreDeviceClaim, true);
});

test('summarizeDispatchResult keeps mixed failed/running dispatch non-terminal', () => {
  const summary = summarizeDispatchResult({
    target_count: 2,
    executions: [
      {
        status: 'failed',
        failure_reason: 'device_claim_failed',
        workflow_id: null
      },
      {
        status: 'running',
        workflow_id: 'exec-2'
      }
    ]
  });

  assert.equal(summary.total, 2);
  assert.equal(summary.failed, 1);
  assert.equal(summary.deviceClaimFailed, 1);
  assert.equal(summary.allTerminal, false);
  assert.equal(summary.allFailed, false);
  assert.equal(summary.allFailuresAreDeviceClaim, false);
});

test('summarizeDispatchResult distinguishes mixed all-failed reasons from all-busy', () => {
  const summary = summarizeDispatchResult({
    target_count: 2,
    executions: [
      {
        status: 'failed',
        failure_reason: 'device_claim_failed'
      },
      {
        status: 'failed',
        failure_reason: 'account_unavailable'
      }
    ]
  });

  assert.equal(summary.total, 2);
  assert.equal(summary.failed, 2);
  assert.equal(summary.deviceClaimFailed, 1);
  assert.equal(summary.allTerminal, true);
  assert.equal(summary.allFailed, true);
  assert.equal(summary.allFailuresAreDeviceClaim, false);
});
