import assert from 'node:assert/strict';
import test from 'node:test';
import {
  automationPrimaryAction,
  automationRunState,
  campaignRunJourney,
  isAlreadyActiveError,
  readinessProblemFromError,
  shouldResumeAutomationReview
} from './automation-start.ts';

test('routes each campaign type to its supported run journey', () => {
  assert.equal(campaignRunJourney(true, true), 'automation');
  assert.equal(campaignRunJourney(true, false), 'dispatch');
  assert.equal(campaignRunJourney(false, false), 'run');
  assert.equal(campaignRunJourney(false, true), 'run');
});

test('maps readiness errors to a useful corrective action', () => {
  const error = (code: string) => ({
    response: { data: { detail: { code } } }
  });

  assert.deepEqual(readinessProblemFromError(error('DEVICE_OFFLINE')), {
    code: 'DEVICE_OFFLINE',
    action: 'devices'
  });
  assert.equal(
    readinessProblemFromError(error('SOURCE_POOL_REQUIRED')).action,
    'source'
  );
  assert.equal(
    readinessProblemFromError(error('DEVICE_TARGETS_REQUIRED')).action,
    'targets'
  );
  assert.equal(
    readinessProblemFromError(error('ACCOUNT_NOT_BOUND')).action,
    'account'
  );
  assert.equal(
    readinessProblemFromError(error('TEMPORAL_UNAVAILABLE')).action,
    'retry'
  );
});

test('reads top-level API codes and safely handles unknown errors', () => {
  assert.deepEqual(
    readinessProblemFromError({
      response: { data: { code: 'DEVICE_NOT_FOUND' } }
    }),
    { code: 'DEVICE_NOT_FOUND', action: 'devices' }
  );
  assert.deepEqual(readinessProblemFromError(new Error('offline')), {
    code: 'UNKNOWN',
    action: 'retry'
  });
});

test('resumes the readiness review only after a repair dialog closes', () => {
  assert.equal(shouldResumeAutomationReview(true, true), false);
  assert.equal(shouldResumeAutomationReview(false, false), false);
  assert.equal(shouldResumeAutomationReview(false, true), true);
});

test('derives automation run state and its primary action from campaign metadata', () => {
  const variables = (status: string) => ({ _continuous_crawl: { status } });
  assert.equal(automationRunState(null), 'inactive');
  assert.equal(automationRunState(variables('running')), 'running');
  assert.equal(automationRunState(variables('unknown')), 'inactive');
  assert.equal(automationPrimaryAction('running'), 'monitor');
  assert.equal(automationPrimaryAction('paused'), 'resume');
  assert.equal(automationPrimaryAction('failed'), 'inspect');
  assert.equal(automationPrimaryAction('completed'), 'setup');
});

test('recognizes a stale-list active-run conflict', () => {
  assert.equal(
    isAlreadyActiveError({
      response: {
        data: { detail: { code: 'CONTINUOUS_CRAWL_ALREADY_ACTIVE' } }
      }
    }),
    true
  );
  assert.equal(isAlreadyActiveError(new Error('conflict')), false);
});
