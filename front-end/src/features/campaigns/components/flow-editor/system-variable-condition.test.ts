import assert from 'node:assert/strict';
import test from 'node:test';

import {
  normalizeSystemVariableCondition,
  PLATFORM_SESSION_READY_VARIABLE
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './system-variable-condition.ts';

test('normalizes the platform session condition to equals true', () => {
  const step = normalizeSystemVariableCondition({
    type: 'if_variable',
    name: PLATFORM_SESSION_READY_VARIABLE,
    greater_than: '',
    then: [],
    else: []
  });

  assert.equal(step.equals, true);
  assert.equal('greater_than' in step, false);
});

test('preserves an explicit false platform session condition', () => {
  const step = normalizeSystemVariableCondition({
    type: 'if_variable',
    name: PLATFORM_SESSION_READY_VARIABLE,
    equals: false,
    then: [],
    else: []
  });

  assert.equal(step.equals, false);
});

test('does not alter user variables', () => {
  const input = {
    type: 'if_variable' as const,
    name: 'CUSTOM_COUNT',
    greater_than: 2,
    then: [],
    else: []
  };

  assert.equal(normalizeSystemVariableCondition(input), input);
});
