import assert from 'node:assert/strict';
import test from 'node:test';

import {
  validateScenarioStepsForApi
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './validate-scenario-steps-for-api.ts';

test('allows if_variable to no-op on then and run login recovery from else', () => {
  const result = validateScenarioStepsForApi([
    { type: 'launch_app', package: 'com.instagram.android' },
    { type: 'platform_session_gate', phase: 'preflight' },
    {
      type: 'if_variable',
      name: 'PLATFORM_SESSION_READY',
      then: [],
      else: [
        {
          type: 'login_if_needed',
          profile: {
            package: 'com.instagram.android',
            semantic_locators: {},
            login_recipe: {
              detect_logged_in: { any_text: [] },
              fields: {},
              submit: { tap_text_any: ['Login', 'Sign in'] }
            }
          }
        }
      ]
    }
  ]);

  assert.deepEqual(result, { ok: true });
});

test('rejects if_variable with no executable branch steps', () => {
  const result = validateScenarioStepsForApi([
    {
      type: 'if_variable',
      name: 'PLATFORM_SESSION_READY',
      then: [],
      else: []
    }
  ]);

  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.match(result.message, /then.*else/);
  }
});
