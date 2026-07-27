import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getInsertMenuForUi
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './constants.ts';
import {
  createDefaultStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../scenario-steps/types.ts';

const translate = (key: string) => key;

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
});
