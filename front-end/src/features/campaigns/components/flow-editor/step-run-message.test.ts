import assert from 'node:assert/strict';
import test from 'node:test';

import { humanizeStepRunMessage } from './step-run-message.ts';

const translate = ((key: string) => {
  const messages: Record<string, string> = {
    'messages.verifiedTargetMissing':
      'Run the target verification step before this action.'
  };
  return messages[key] ?? key;
}) as Parameters<typeof humanizeStepRunMessage>[1];

test('explains a missing verified target without exposing the runtime contract', () => {
  assert.equal(
    humanizeStepRunMessage(
      "content_interaction: require_verified_target='_post_target' was not verified by a target resolver",
      translate
    ),
    'Run the target verification step before this action.'
  );
});
