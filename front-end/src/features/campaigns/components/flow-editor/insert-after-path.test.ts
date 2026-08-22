import assert from 'node:assert/strict';
import test from 'node:test';
import { insertStepAtPath } from './insert-step-at-path.ts';
import type { FlowStep } from '../scenario-steps/types.ts';

/**
 * `insertStepAtPath` splices *at* the index, so "insert after" is the same call
 * with the last index bumped by one. This mirrors `insertAfterPath` in
 * flow-editor.tsx — the "use this result" action depends on the new step
 * landing directly below the one that produced the value, not above it.
 */
function insertAfter(
  steps: FlowStep[],
  path: Array<{ listKey: string; ci: number }>,
  step: FlowStep
): FlowStep[] {
  const last = path[path.length - 1]!;
  const after = [...path.slice(0, -1), { ...last, ci: last.ci + 1 }];
  return insertStepAtPath(steps, after as never, step);
}

const s = (type: string, id?: string) =>
  ({ type, ...(id ? { id } : {}) }) as unknown as FlowStep;

test('inserts directly below the source step, not above it', () => {
  const steps = [s('extract_text_ocr', 'a'), s('tap', 'b')];
  const next = insertAfter(
    steps,
    [{ listKey: 'steps', ci: 0 }],
    s('if_variable')
  );
  assert.deepEqual(
    next.map((x) => x.type),
    ['extract_text_ocr', 'if_variable', 'tap']
  );
});

test('appends when the source step is last', () => {
  const steps = [s('tap', 'a'), s('extract_text_ocr', 'b')];
  const next = insertAfter(
    steps,
    [{ listKey: 'steps', ci: 1 }],
    s('if_variable')
  );
  assert.deepEqual(
    next.map((x) => x.type),
    ['tap', 'extract_text_ocr', 'if_variable']
  );
});

test('does not mutate the original list', () => {
  const steps = [s('extract_text_ocr', 'a')];
  const copy = JSON.parse(JSON.stringify(steps));
  insertAfter(steps, [{ listKey: 'steps', ci: 0 }], s('if_variable'));
  assert.deepEqual(JSON.parse(JSON.stringify(steps)), copy);
});
