import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  canPersistScenario,
  resolveStepEditOverlayHost,
  shouldUseChildStepDialog,
  shouldUseStepEditOverlay,
  STEP_EDIT_OVERLAY_HOST_SELECTOR
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './nested-step-edit.ts';
import { Z_FLOATING } from '../../../../lib/z-index.ts';

test('nested step editor z-index contract sits above default dialog layer', () => {
  assert.equal(Z_FLOATING, 10050);
  assert.ok(Z_FLOATING > 9999);
});

test('nested step editor avoids a nested Radix Presence layer', () => {
  const source = readFileSync(
    new URL('./step-edit-overlay.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /createPortal/);
  assert.match(source, /resolveStepEditOverlayHost/);
  assert.doesNotMatch(source, /from '@\/components\/ui\/dialog'/);
});

test('nested step editor portal stays inside its parent modal focus scope', () => {
  const modalHost = {} as HTMLElement;
  const fallback = {} as HTMLElement;
  const anchor = {
    closest(selector: string) {
      assert.equal(selector, STEP_EDIT_OVERLAY_HOST_SELECTOR);
      return modalHost;
    }
  } as Pick<Element, 'closest'>;

  assert.equal(resolveStepEditOverlayHost(anchor, fallback), modalHost);
  assert.equal(resolveStepEditOverlayHost(null, fallback), fallback);
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

test('scenario persistence waits until the nested child edit is committed', () => {
  assert.equal(canPersistScenario(true), false);
  assert.equal(canPersistScenario(false), true);
});
