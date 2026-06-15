import assert from 'node:assert/strict';
import test from 'node:test';

import type { FlowStep } from '../scenario-steps/types';
import { applyTapPointToSteps } from './coordinate-pick.ts';
import {
  decodeScenarioInlineRunKey,
  encodeScenarioInlineRunKey,
  resolveLatestStepForInlineRun,
  resolveStepForInlineRunKey
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './inline-run-key.ts';

test('encode/decode round-trip for nested else tap_ratio', () => {
  const path = [{ listKey: 'else', childIndex: 0 }];
  const key = encodeScenarioInlineRunKey(1, path);
  assert.equal(key, '1/else:0');
  assert.deepEqual(decodeScenarioInlineRunKey(key), { rootIndex: 1, path });
});

test('resolveStepForInlineRunKey reads mirror-updated tap_ratio in else branch', () => {
  const steps: FlowStep[] = [
    { type: 'wait', seconds: 1 },
    {
      type: 'if_element',
      by: 'description',
      value: 'Search',
      then: [{ type: 'wait', seconds: 0.5 }],
      else: [{ type: 'tap_ratio', x: 0.87, y: 0.035 }]
    }
  ];
  const runKey = encodeScenarioInlineRunKey(1, [
    { listKey: 'else', childIndex: 0 }
  ]);
  const resolved = resolveStepForInlineRunKey(steps, runKey);
  assert.ok(resolved);
  assert.equal(resolved.type, 'tap_ratio');
  assert.equal((resolved as { x?: number }).x, 0.87);
  assert.equal((resolved as { y?: number }).y, 0.035);
});

test('mirror tap pick then run resolves new coords over stale StepCard snapshot', () => {
  const path = [{ listKey: 'else', childIndex: 0 }];
  const runKey = encodeScenarioInlineRunKey(1, path);
  const pickTarget = { rootIndex: 1, path, mode: 'tap_point' as const };
  const steps: FlowStep[] = [
    { type: 'wait', seconds: 1 },
    {
      type: 'if_element',
      by: 'description',
      value: 'Search',
      then: [],
      else: [{ type: 'tap_ratio', x: 0.05, y: 0.05 }]
    }
  ];
  const staleCardSnapshot = (steps[1] as { else: FlowStep[] }).else[0]!;
  const afterPick = applyTapPointToSteps(steps, pickTarget, 0.87, 0.035);
  const forRun = resolveLatestStepForInlineRun(
    afterPick,
    runKey,
    staleCardSnapshot
  );
  assert.equal(forRun.type, 'tap_ratio');
  assert.equal((forRun as { x?: number }).x, 0.87);
  assert.equal((forRun as { y?: number }).y, 0.035);
});

test('pick target path matches inline run key for nested then branch', () => {
  const path = [{ listKey: 'then', childIndex: 0 }];
  const runKey = encodeScenarioInlineRunKey(0, path);
  const pickTarget = { rootIndex: 0, path, mode: 'tap_point' as const };
  const steps: FlowStep[] = [
    {
      type: 'if_element',
      by: 'description',
      value: 'Btn',
      then: [{ type: 'tap_ratio', x: 0.1, y: 0.2 }],
      else: []
    }
  ];
  const afterPick = applyTapPointToSteps(steps, pickTarget, 0.55, 0.66);
  const resolved = resolveStepForInlineRunKey(afterPick, runKey);
  assert.equal((resolved as { x?: number }).x, 0.55);
  assert.equal((resolved as { y?: number }).y, 0.66);
});
