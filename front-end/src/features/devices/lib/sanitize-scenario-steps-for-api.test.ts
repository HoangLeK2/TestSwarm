import assert from 'node:assert/strict';
import test from 'node:test';

import {
  sanitizeScenarioStepsForApi
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './sanitize-scenario-steps-for-api.ts';

test('scenario sanitizer preserves explicit empty random branches', () => {
  const sanitized = sanitizeScenarioStepsForApi([
    {
      id: 'random-id',
      order: 'a0',
      _id: 'react-id',
      _fgId: 'random-id',
      type: 'random_pick',
      branches: [
        { weight: 3, steps: [] },
        {
          weight: 1,
          steps: [
            {
              id: 'wait-id',
              order: 'a0',
              _id: 'nested-react-id',
              _fgId: 'wait-id',
              type: 'wait',
              seconds: 1
            }
          ]
        }
      ]
    }
  ]);

  assert.equal(sanitized[0]?.branches.length, 2);
  assert.deepEqual(sanitized[0]?.branches[0], { weight: 3, steps: [] });
  assert.equal(sanitized[0]?._id, undefined);
  assert.equal(sanitized[0]?._fgId, undefined);
  assert.equal(sanitized[0]?.branches[1]?.steps[0]?._id, undefined);
  assert.equal(sanitized[0]?.branches[1]?.steps[0]?._fgId, undefined);
});
