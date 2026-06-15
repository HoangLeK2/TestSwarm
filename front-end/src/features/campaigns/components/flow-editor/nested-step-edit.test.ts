import assert from 'node:assert/strict';
import test from 'node:test';

import {
  shouldUseChildStepDialog,
  shouldUseStepEditOverlay
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './nested-step-edit.ts';
import { Z_FLOATING } from '../../../../lib/z-index.ts';

test('nested step editor z-index contract sits above default dialog layer', () => {
  assert.equal(Z_FLOATING, 10050);
  assert.ok(Z_FLOATING > 9999);
});

test('shouldUseStepEditOverlay enables editor in scenario dialog (nested + compact)', () => {
  assert.equal(shouldUseStepEditOverlay(true, true), true);
});

test('shouldUseStepEditOverlay enables editor in template dialog (nested only)', () => {
  assert.equal(shouldUseStepEditOverlay(true, false), true);
});

test('shouldUseStepEditOverlay enables editor in compact preview without nestedInDialog', () => {
  assert.equal(shouldUseStepEditOverlay(false, true), true);
});

test('shouldUseStepEditOverlay defers to standalone dialog in control-record list mode', () => {
  assert.equal(shouldUseStepEditOverlay(false, false), false);
});

test('shouldUseChildStepDialog is mutually exclusive with overlay mode', () => {
  const cases: Array<[boolean, boolean]> = [
    [true, true],
    [true, false],
    [false, true],
    [false, false]
  ];
  for (const [nestedInDialog, compact] of cases) {
    assert.equal(
      shouldUseStepEditOverlay(nestedInDialog, compact) ||
        shouldUseChildStepDialog(nestedInDialog, compact),
      true,
      `expected overlay or dialog for nested=${nestedInDialog} compact=${compact}`
    );
    assert.notEqual(
      shouldUseStepEditOverlay(nestedInDialog, compact),
      shouldUseChildStepDialog(nestedInDialog, compact),
      `overlay and dialog must not both be true for nested=${nestedInDialog} compact=${compact}`
    );
  }
});
