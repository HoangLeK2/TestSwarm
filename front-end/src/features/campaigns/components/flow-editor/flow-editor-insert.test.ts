import test from 'node:test';
import assert from 'node:assert/strict';
import { insertStepAtPath } from './insert-step-at-path';
import type { FlowStep } from '../scenario-steps/types.ts';

const wait = (seconds: number): FlowStep => ({ type: 'wait', seconds });

test('inserts before a root step', () => {
  const result = insertStepAtPath(
    [wait(1), wait(3)],
    [{ listKey: 'steps', ci: 1 }],
    wait(2)
  );

  assert.deepEqual(
    result.map((step) => step.seconds),
    [1, 2, 3]
  );
});

test('inserts into the same conditional branch as the target row', () => {
  const result = insertStepAtPath(
    [{ type: 'if', then: [wait(1), wait(3)], else: [] }],
    [
      { listKey: 'steps', ci: 0 },
      { listKey: 'then', ci: 1 }
    ],
    wait(2)
  );

  assert.deepEqual(
    result[0]?.then?.map((step: FlowStep) => step.seconds),
    [1, 2, 3]
  );
  assert.deepEqual(result[0]?.else, []);
});

test('inserts into the same random branch as the target row', () => {
  const result = insertStepAtPath(
    [
      {
        type: 'random_pick',
        branches: [
          { weight: 1, steps: [wait(1)] },
          { weight: 1, steps: [wait(3)] }
        ]
      }
    ],
    [
      { listKey: 'steps', ci: 0 },
      { listKey: 'branches.1', ci: 0 }
    ],
    wait(2)
  );

  assert.deepEqual(
    result[0]?.branches?.[0]?.steps.map((step: FlowStep) => step.seconds),
    [1]
  );
  assert.deepEqual(
    result[0]?.branches?.[1]?.steps.map((step: FlowStep) => step.seconds),
    [2, 3]
  );
});

test('appends into an empty then branch from a branch row path', () => {
  const result = insertStepAtPath(
    [{ type: 'if_variable', then: [], else: [] }],
    [
      { listKey: 'steps', ci: 0 },
      { listKey: 'then', ci: 0 }
    ],
    wait(2)
  );

  assert.deepEqual(
    result[0]?.then?.map((step: FlowStep) => step.seconds),
    [2]
  );
  assert.deepEqual(result[0]?.else, []);
});

test('appends into an empty else branch from a branch row path', () => {
  const result = insertStepAtPath(
    [{ type: 'if_variable', then: [], else: [] }],
    [
      { listKey: 'steps', ci: 0 },
      { listKey: 'else', ci: 0 }
    ],
    wait(2)
  );

  assert.deepEqual(result[0]?.then, []);
  assert.deepEqual(
    result[0]?.else?.map((step: FlowStep) => step.seconds),
    [2]
  );
});

test('appends into an empty loop body from a branch row path', () => {
  const result = insertStepAtPath(
    [{ type: 'loop', count: 3, steps: [] }],
    [
      { listKey: 'steps', ci: 0 },
      { listKey: 'steps', ci: 0 }
    ],
    wait(2)
  );

  assert.deepEqual(
    result[0]?.steps?.map((step: FlowStep) => step.seconds),
    [2]
  );
});

test('appends into an empty random branch from a branch row path', () => {
  const result = insertStepAtPath(
    [{ type: 'random_pick', branches: [{ weight: 1, steps: [] }] }],
    [
      { listKey: 'steps', ci: 0 },
      { listKey: 'branches.0', ci: 0 }
    ],
    wait(2)
  );

  assert.deepEqual(
    result[0]?.branches?.[0]?.steps.map((step: FlowStep) => step.seconds),
    [2]
  );
});
