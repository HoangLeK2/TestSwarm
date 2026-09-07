import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { performance } from 'node:perf_hooks';
import test from 'node:test';

import type { FlowStep } from '../scenario-steps/types';
import {
  resolveStepAtPath,
  updateStepAtPath,
  walkFlowStepsWithPaths,
  amplifyLoopSteps
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-tree-walk.ts';
import {
  findStepByFlowgramId,
  patchStepByFlowgramId
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../../../scenario-templates/components/scenario-flow-editor/patch-step-tree.ts';

const __dir = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dir, '../../../../../../');

function loadSteps(): FlowStep[] {
  const raw = JSON.parse(
    readFileSync(
      join(
        REPO_ROOT,
        'front-end/src/features/campaigns/components/flow-editor/fixtures/crawl-group-3.json'
      ),
      'utf8'
    )
  ) as { scenario: { body: { steps: FlowStep[] } } };
  return raw.scenario.body.steps;
}

function bench(
  label: string,
  fn: () => void,
  iterations: number,
  maxMs: number
) {
  for (let i = 0; i < Math.min(100, iterations); i++) fn();
  const samples = Array.from({ length: 5 }, () => {
    const t0 = performance.now();
    for (let i = 0; i < iterations; i++) fn();
    return performance.now() - t0;
  }).sort((a, b) => a - b);
  const best = samples[0] ?? 0;
  const median = samples[Math.floor(samples.length / 2)] ?? best;
  const perOpUs = (median * 1000) / iterations;
  assert.ok(
    median < maxMs || best < maxMs * 0.8,
    `${label}: median ${median.toFixed(2)}ms, best ${best.toFixed(2)}ms for ${iterations} ops (${perOpUs.toFixed(1)}µs/op) exceeds ${maxMs}ms budget`
  );
  return { elapsed: median, perOpUs };
}

test('perf: walkFlowStepsWithPaths stays fast on real crawl scenario', () => {
  const steps = loadSteps();
  const visits = walkFlowStepsWithPaths(steps);
  assert.ok(visits.length >= 20, `expected many nodes, got ${visits.length}`);
  bench(
    'walkFlowStepsWithPaths',
    () => walkFlowStepsWithPaths(steps),
    5000,
    80
  );
});

test('perf: resolveStepAtPath for deepest comment extract stays fast', () => {
  const steps = loadSteps();
  const extractVisit = walkFlowStepsWithPaths(steps).find(
    (v) => v.step.type === 'extract' && v.step.entity === 'comments'
  );
  assert.ok(extractVisit);
  const path = extractVisit.path;
  bench(
    'resolveStepAtPath (deep extract)',
    () => resolveStepAtPath(steps, path),
    10000,
    50
  );
});

test('perf: updateStepAtPath on comment extract stays fast', () => {
  const steps = loadSteps();
  const extractVisit = walkFlowStepsWithPaths(steps).find(
    (v) => v.step.type === 'extract' && v.step.entity === 'comments'
  );
  assert.ok(extractVisit);
  const { step, path } = extractVisit;
  bench(
    'updateStepAtPath (comment extract)',
    () =>
      updateStepAtPath(steps, path, {
        ...step,
        max_items: (step.max_items as number) + 1
      } as FlowStep),
    2000,
    100
  );
});

test('perf: patchStepByFlowgramId on amplified loop stays fast', () => {
  const base = loadSteps();
  const amplified = amplifyLoopSteps(base, 20);
  const visits = walkFlowStepsWithPaths(amplified);
  assert.ok(
    visits.length >= 200,
    `expected amplified tree, got ${visits.length}`
  );

  const withFg = amplified.map((s) => {
    if (s.type !== 'loop') return s;
    return {
      ...s,
      steps: ((s as FlowStep & { steps?: FlowStep[] }).steps ?? []).map(
        (c, i) => ({
          ...c,
          _fgId: `node-${i}`
        })
      )
    } as FlowStep;
  });
  const targetFg = 'node-1';
  const target = findStepByFlowgramId(withFg, targetFg);
  assert.ok(target);

  bench(
    'patchStepByFlowgramId (amplified x20 loop)',
    () =>
      patchStepByFlowgramId(withFg, targetFg, {
        ...target,
        timeout: 9
      } as FlowStep),
    1000,
    80
  );
});

test('perf summary logs node count and budgets', () => {
  const steps = loadSteps();
  const visits = walkFlowStepsWithPaths(steps);
  const extract = visits.find(
    (v) => v.step.type === 'extract' && v.step.entity === 'comments'
  );
  assert.ok(extract);
  const walk = bench(
    'walk (report)',
    () => walkFlowStepsWithPaths(steps),
    1000,
    30
  );
  const resolve = bench(
    'resolve (report)',
    () => resolveStepAtPath(steps, extract.path),
    5000,
    30
  );
  // eslint-disable-next-line no-console
  console.log(
    `[step-tree-perf] nodes=${visits.length} depth=${extract.depth} ` +
      `walk=${walk.perOpUs.toFixed(1)}µs/op resolve=${resolve.perOpUs.toFixed(1)}µs/op`
  );
});
